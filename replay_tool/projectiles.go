package main

// Preserve projectile user messages and same-callback entity candidates. These
// messages describe a replay source, not player exposure, damage or a hit.
import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"io"
	"os"
	"sort"
	"strings"
)

const projectileSchema = "replay-projectiles.v1"
const projectileContext = "raw_index_and_handle_candidates_same_callback.v1"

var projectileCallbacks = []string{
	"dota.CDOTAUserMsg_TE_Projectile",
	"dota.CDOTAUserMsg_TE_ProjectileLoc",
	"dota.CDOTAUserMsg_TE_DestroyProjectile",
	"dota.CDOTAUserMsg_CreateLinearProjectile",
	"dota.CDOTAUserMsg_DestroyLinearProjectile",
	"dota.CDOTAUserMsg_DodgeTrackingProjectiles",
	"dota.CDOTAUserMsg_UpdateLinearProjectileCPData",
}

func projectileReferences(m proto.Message) map[string]uint64 {
	refs := map[string]uint64{}
	m.ProtoReflect().Range(func(f protoreflect.FieldDescriptor, v protoreflect.Value) bool {
		name := string(f.Name())
		if name != "source" && name != "target" && name != "ability" && name != "entindex" {
			return true
		}
		switch f.Kind() {
		case protoreflect.Uint32Kind:
			refs[name] = v.Uint()
		case protoreflect.Int32Kind:
			if v.Int() >= 0 {
				refs[name] = uint64(v.Int())
			}
		}
		return true
	})
	return refs
}

func projectileEntity(e *manta.Entity) map[string]interface{} {
	receipt := entityReceipt(e)
	fields, types := map[string]interface{}{}, map[string]string{}
	for _, key := range []string{"m_iHealth", "m_iMaxHealth", "m_flMana", "m_flMaxMana", "m_iTeamNum", "m_iPlayerID", "m_lifeState", "m_bIsIllusion",
		"CBodyComponent.m_cellX", "CBodyComponent.m_cellY", "CBodyComponent.m_cellZ", "CBodyComponent.m_vecX", "CBodyComponent.m_vecY", "CBodyComponent.m_vecZ"} {
		raw := e.Get(key)
		if raw == nil {
			continue
		}
		if clean, ok := traceScalar(raw); ok {
			fields[key], types[key] = clean, fmt.Sprintf("%T", raw)
		}
	}
	receipt["fields"], receipt["field_types"] = fields, types
	return receipt
}

func projectileSnapshot(c *orderContext, m proto.Message) map[string]interface{} {
	refs, indices := map[string]interface{}{}, map[int32]bool{}
	for name, raw := range projectileReferences(m) {
		candidate := map[string]interface{}{"raw_value": raw, "index_candidate": nil, "handle_candidate": nil}
		if raw <= 16383 {
			if e := c.find(int32(raw)); e != nil {
				candidate["index_candidate"] = projectileEntity(e)
				indices[e.GetIndex()] = true
			}
		}
		if e := c.handle(raw); e != nil {
			candidate["handle_candidate"] = projectileEntity(e)
			indices[e.GetIndex()] = true
		}
		refs[name] = candidate
	}
	selected := []map[string]interface{}{}
	resourceIndices := []int{}
	for index := range c.resources {
		resourceIndices = append(resourceIndices, int(index))
	}
	sort.Ints(resourceIndices)
	for _, index := range resourceIndices {
		resource := c.resources[int32(index)]
		// A replaced resource is not a valid identity source.
		if c.find(int32(index)) != resource {
			continue
		}
		for slot := 0; slot < 64; slot++ {
			key := fmt.Sprintf("m_vecPlayerTeamData.%04d.m_hSelectedHero", slot)
			h, present := rawUnsigned(resource.Get(key))
			if !present {
				continue
			}
			hero := c.handle(h)
			if hero == nil || !indices[hero.GetIndex()] || !strings.HasPrefix(hero.GetClassName(), heroPrefix) {
				continue
			}
			steamKey := fmt.Sprintf("m_vecPlayerData.%04d.m_iPlayerSteamID", slot)
			var steam interface{}
			if v, known := rawUnsigned(resource.Get(steamKey)); known {
				steam = v
			}
			selected = append(selected, map[string]interface{}{"resource": entityReceipt(resource), "resource_slot": slot,
				"selected_handle": h, "selected_property": key, "steam_id": steam, "steam_property": steamKey, "hero": entityReceipt(hero)})
		}
	}
	return map[string]interface{}{"semantics": projectileContext, "field_references": refs, "selected_heroes": selected}
}

type projectileWriter struct {
	p                *manta.Parser
	context          *orderContext
	enc              *json.Encoder
	record, sequence uint64
	tick             uint32
	counts           map[string]uint64
}

func (w *projectileWriter) emit(kind string, fields map[string]interface{}) error {
	if w.tick != w.p.Tick {
		w.tick, w.sequence = w.p.Tick, 0
	}
	w.record++
	w.sequence++
	fields["t"], fields["record_index"] = kind, w.record
	fields["demo_tick"], fields["net_tick"], fields["sequence_in_tick"] = w.p.Tick, w.p.NetTick, w.sequence
	fields["game_time"], fields["available_to_player_at"], fields["validation"] = nil, nil, "unverified_source_observation"
	return w.enc.Encode(fields)
}
func (w *projectileWriter) message(m proto.Message) error {
	data, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(m)
	if err != nil {
		return err
	}
	name := string(m.ProtoReflect().Descriptor().FullName())
	fields := map[string]interface{}{"protobuf_type": name, "data": json.RawMessage(data),
		"protobuf_unknown_fields_hex": hex.EncodeToString(m.ProtoReflect().GetUnknown()),
		"entity_context":              projectileSnapshot(w.context, m), "impact_time": nil, "damage": nil, "screen_cue": nil}
	if err = w.emit("projectile_message", fields); err != nil {
		return err
	}
	w.counts[name]++
	return nil
}
func runProjectiles(path string, output io.Writer) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	size, err := io.Copy(h, f)
	if err != nil {
		return err
	}
	if _, err = f.Seek(0, io.SeekStart); err != nil {
		return err
	}
	p, err := manta.NewStreamParser(f)
	if err != nil {
		return err
	}
	b := bufio.NewWriterSize(output, 1<<20)
	defer b.Flush()
	counts := map[string]uint64{}
	for _, name := range projectileCallbacks {
		counts[name] = 0
	}
	c := newOrderContext(p)
	p.OnEntity(c.update)
	w := &projectileWriter{p: p, context: c, enc: json.NewEncoder(b), counts: counts}
	sha := hex.EncodeToString(h.Sum(nil))
	meta := map[string]interface{}{"schema_version": projectileSchema, "extractor_name": "manta", "extractor_version": traceVersion, "manta_version": "v1.5.0",
		"replay_sha256": sha, "replay_bytes": size, "source_callbacks": projectileCallbacks, "context_semantics": projectileContext,
		"completeness": "registered_source_callback_census_only", "timebase_version": "raw-demo-net-ticks.v1",
		"sequence_semantics": "callback_stream_order_not_verified_simulation_order",
		"warnings": []string{"projectile_messages_do_not_establish_damage_or_successful_hit", "source_target_fields_have_unverified_index_or_handle_semantics",
			"projectile_pool_handle_is_not_entity_handle", "player_visibility_and_attention_unavailable", "raw_ticks_and_launch_tick_have_no_verified_game_clock", "entity_snapshot_may_precede_same_packet_entity_update_not_current_simulation_state"}}
	if err = w.emit("meta", meta); err != nil {
		return err
	}
	p.Callbacks.OnCDOTAUserMsg_TE_Projectile(func(m *dota.CDOTAUserMsg_TE_Projectile) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_TE_ProjectileLoc(func(m *dota.CDOTAUserMsg_TE_ProjectileLoc) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_TE_DestroyProjectile(func(m *dota.CDOTAUserMsg_TE_DestroyProjectile) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_CreateLinearProjectile(func(m *dota.CDOTAUserMsg_CreateLinearProjectile) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_DestroyLinearProjectile(func(m *dota.CDOTAUserMsg_DestroyLinearProjectile) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_DodgeTrackingProjectiles(func(m *dota.CDOTAUserMsg_DodgeTrackingProjectiles) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_UpdateLinearProjectileCPData(func(m *dota.CDOTAUserMsg_UpdateLinearProjectileCPData) error { return w.message(m) })
	if err = p.Start(); err != nil {
		return err
	}
	footer := map[string]interface{}{"schema_version": projectileSchema, "extractor_name": "manta", "extractor_version": traceVersion, "manta_version": "v1.5.0",
		"replay_sha256": sha, "replay_bytes": size, "counts": counts, "message_count": w.record - 1, "parser_completed": true, "game_build": p.GameBuild}
	if err = w.emit("projectiles_end", footer); err != nil {
		return err
	}
	return b.Flush()
}
