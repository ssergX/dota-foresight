package main

// The trace is a source-observation stream, NOT a verified gameplay model.
// A decoded field is preserved with its original path/type; missing fields stay
// absent. Manta callback order is not represented as simulation sub-tick order.
import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"reflect"
	"sort"
	"strconv"
	"strings"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const traceVersion = "foresight-replay/3.1"

// Resource array indices are retained as source identities. Whether these map
// to a provider's player_slot is a separate, externally checked join.
func selectedHeroHandles(m map[string]interface{}) map[int]uint64 {
	out := map[int]uint64{}
	for key, raw := range m {
		parts := strings.Split(key, ".")
		if len(parts) != 3 || parts[0] != "m_vecPlayerTeamData" || parts[2] != "m_hSelectedHero" {
			continue
		}
		slot, err := strconv.Atoi(parts[1])
		if err != nil || slot < 0 || slot > 63 {
			continue
		}
		switch v := raw.(type) {
		case uint64:
			out[slot] = v
		case uint32:
			out[slot] = uint64(v)
		case int32:
			if v >= 0 {
				out[slot] = uint64(v)
			}
		}
	}
	return out
}

func traceClass(class string) bool {
	return strings.HasPrefix(class, "CDOTA_Unit_") ||
		strings.HasPrefix(class, "CDOTA_BaseNPC") || strings.HasPrefix(class, "CDOTA_NPC_") ||
		strings.HasPrefix(class, "CDOTA_Item") || strings.HasPrefix(class, "CDOTA_Ability") ||
		class == "CDOTAGamerulesProxy" || class == "CDOTA_PlayerResource" ||
		class == "CDOTAPlayerController" || class == "CDOTAPlayer" ||
		strings.Contains(class, "DOTA") && (strings.Contains(class, "Tower") || strings.Contains(class, "Barracks") || strings.Contains(class, "Building"))
}

// Keep gameplay state without per-tick animation/render cosmetics. All fields
// on resource, rules and item/ability classes are retained because their schema
// varies across patches. This explicit projection is versioned in metadata.
func traceField(class, key string) bool {
	if class == "CDOTAGamerulesProxy" || class == "CDOTA_PlayerResource" ||
		strings.HasPrefix(class, "CDOTA_Item") || strings.HasPrefix(class, "CDOTA_Ability") {
		return true
	}
	for _, token := range []string{"m_cell", "m_vecX", "m_vecY", "m_vecZ", "m_angRotation",
		"Health", "Mana", "Level", "XP", "PlayerID", "TeamNum", "lifeState", "Owner", "owner",
		"Abilities", "Inventory", "Item", "Ability", "Cooldown", "Charge", "Modifier", "State",
		"Visible", "Visibility", "FoW", "Vision", "Invisible", "Illusion", "Replicat", "Clone",
		"Controll", "Move", "Speed", "Attack", "Target", "Channel", "Cast", "Stun", "Silenc",
		"Root", "Teleport", "Buyback", "Gold", "Armor", "Resistance", "Respawn", "Reincarn",
		"SelectedHero", "UnitName", "UnitLabel", "IsHero", "IsSummon", "CommandRestricted"} {
		if strings.Contains(key, token) {
			return true
		}
	}
	return false
}

// encoding/json otherwise rounds 64-bit IDs in JavaScript. Preserve their exact
// decimal spelling and type; ordinary finite floats remain numbers.
func traceScalar(v interface{}) (interface{}, bool) {
	switch x := v.(type) {
	case uint64:
		return strconv.FormatUint(x, 10), true
	case int64:
		return strconv.FormatInt(x, 10), true
	case float32:
		if math.IsNaN(float64(x)) || math.IsInf(float64(x), 0) {
			return nil, false
		}
	case float64:
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return nil, false
		}
	case []float32:
		for _, n := range x {
			if math.IsNaN(float64(n)) || math.IsInf(float64(n), 0) {
				return nil, false
			}
		}
	}
	if _, err := json.Marshal(v); err != nil {
		return nil, false
	}
	return v, true
}

type traceState struct {
	fields map[string]interface{}
	types  map[string]string
}

func projectTrace(class string, raw map[string]interface{}) (traceState, []string) {
	s := traceState{map[string]interface{}{}, map[string]string{}}
	issues := []string{}
	for key, value := range raw {
		if !traceField(class, key) {
			continue
		}
		clean, ok := traceScalar(value)
		if !ok {
			issues = append(issues, key+":non_json_or_nonfinite_value")
			clean = nil
		}
		s.fields[key] = clean
		s.types[key] = fmt.Sprintf("%T", value)
	}
	sort.Strings(issues)
	return s, issues
}

func traceDelta(previous, current traceState, full bool) (map[string]interface{}, map[string]string, []string) {
	fields, types := map[string]interface{}{}, map[string]string{}
	removed := []string{}
	for key, value := range current.fields {
		old, present := previous.fields[key]
		if full || !present || previous.types[key] != current.types[key] || !reflect.DeepEqual(old, value) {
			fields[key], types[key] = value, current.types[key]
		}
	}
	for key := range previous.fields {
		if _, ok := current.fields[key]; !ok {
			removed = append(removed, key)
		}
	}
	sort.Strings(removed)
	return fields, types, removed
}

type traceWriter struct {
	p        *manta.Parser
	enc      *json.Encoder
	record   uint64
	tick     uint32
	sequence uint64
	counts   map[string]uint64
}

func (w *traceWriter) emit(kind string, fields map[string]interface{}) error {
	if w.p.Tick != w.tick {
		w.tick, w.sequence = w.p.Tick, 0
	}
	w.record++
	w.sequence++
	fields["t"], fields["record_index"] = kind, w.record
	fields["demo_tick"], fields["net_tick"], fields["sequence_in_tick"] = w.p.Tick, w.p.NetTick, w.sequence
	fields["game_time"] = nil // No tick/30 assumption and no retrospective clock backfill.
	w.counts[kind]++
	return w.enc.Encode(fields)
}

func (w *traceWriter) message(kind string, message proto.Message) error {
	data, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(message)
	if err != nil {
		return err
	}
	return w.emit(kind, map[string]interface{}{"data": json.RawMessage(data)})
}

func (w *traceWriter) combatMessage(message *dota.CMsgDOTACombatLogEntry) error {
	data, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(message)
	if err != nil {
		return err
	}
	names := map[string]string{}
	for key, index := range map[string]*uint32{
		"attacker_name": message.AttackerName, "target_name": message.TargetName,
		"inflictor_name": message.InflictorName, "target_source_name": message.TargetSourceName,
		"damage_source_name": message.DamageSourceName,
	} {
		if index != nil {
			if name, ok := w.p.LookupStringByIndex("CombatLogNames", int32(*index)); ok {
				names[key] = name
			}
		}
	}
	return w.emit("combat_log", map[string]interface{}{"data": json.RawMessage(data),
		"resolved_names": names, "name_resolution": "CombatLogNames_at_callback/v1"})
}

// A lightweight second pass can enrich an existing v3 trace. Consumers must
// check replay SHA, every combat payload and ordinal, and completion counts;
// names are resolved at each callback, never from the final string table.
func runCombatNames(path string, output io.Writer) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
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
	w := &traceWriter{p: p, enc: json.NewEncoder(b), counts: map[string]uint64{}}
	if err = w.emit("meta", map[string]interface{}{"schema_version": "replay-combat-names.v1",
		"replay_sha256": hex.EncodeToString(h.Sum(nil)), "extractor_version": traceVersion,
		"manta_version": "v1.5.0", "validation": "unverified"}); err != nil {
		return err
	}
	p.Callbacks.OnCMsgDOTACombatLogEntry(func(m *dota.CMsgDOTACombatLogEntry) error { return w.combatMessage(m) })
	if err = p.Start(); err != nil {
		_ = b.Flush()
		return err
	}
	if err = w.emit("trace_end", map[string]interface{}{"parser_completed": true, "counts": w.counts,
		"game_build": p.GameBuild, "validation": "unverified"}); err != nil {
		return err
	}
	return b.Flush()
}

func runTrace(path string, output io.Writer) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
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
	w := &traceWriter{p: p, enc: json.NewEncoder(b), counts: map[string]uint64{}}
	if err = w.emit("meta", map[string]interface{}{
		"schema_version": "replay-trace.v3", "extractor_name": "manta", "extractor_version": traceVersion,
		"manta_version": "v1.5.0", "replay_sha256": hex.EncodeToString(h.Sum(nil)),
		"validation": "unverified", "completeness": "projected_entity_delta_stream",
		"field_projection": "gameplay-fields.v1", "timebase_version": "raw-demo-net-ticks-and-gamerules.v1",
		"sequence_semantics": "callback_stream_order_not_verified_simulation_order",
		"warnings": []string{"raw_fields_are_not_validated_gameplay_facts", "game_time_mapping_requires_prefix_clock_evidence",
			"screen_attention_unavailable", "visibility_bits_are_raw_not_verified_fog_of_war",
			"modifier_table_omits_empty_deletions_use_combat_remove_events", "combat_bulk_delivery_time_is_not_event_time"},
	}); err != nil {
		return err
	}
	states := map[string]traceState{}
	mappings := map[int]uint64{}
	mappingSignatures := map[int]string{}
	// Reattempt unresolved handles as entities are created; resolution never uses
	// future entities to rewrite a previously emitted observation.
	emitMappings := func() error {
		slots := make([]int, 0, len(mappings))
		for slot := range mappings {
			slots = append(slots, slot)
		}
		sort.Ints(slots)
		for _, slot := range slots {
			handle := mappings[slot]
			record := map[string]interface{}{"resource_slot": slot, "selected_hero_handle": strconv.FormatUint(handle, 10),
				"mapping_property": fmt.Sprintf("m_vecPlayerTeamData.%04d.m_hSelectedHero", slot),
				"entity_index":     nil, "generation": nil, "status": "unresolved_handle"}
			if e := p.FindEntityByHandle(handle); e != nil && strings.HasPrefix(e.GetClassName(), heroPrefix) {
				record["entity_index"], record["generation"], record["status"] = e.GetIndex(), e.GetSerial(), "resolved_handle"
			}
			sig, _ := json.Marshal(record)
			if mappingSignatures[slot] != string(sig) {
				mappingSignatures[slot] = string(sig)
				if err := w.emit("player_mapping", record); err != nil {
					return err
				}
			}
		}
		return nil
	}
	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		class := e.GetClassName()
		if !traceClass(class) {
			return nil
		}
		key := fmt.Sprintf("%d:%d", e.GetIndex(), e.GetSerial())
		raw := e.Map()
		current, issues := projectTrace(class, raw)
		previous, present := states[key]
		full := !present || op.Flag(manta.EntityOpCreated)
		fields, types, removed := traceDelta(previous, current, full)
		if full || len(fields) > 0 || len(removed) > 0 || op != manta.EntityOpUpdated {
			if err := w.emit("entity", map[string]interface{}{"entity_index": e.GetIndex(), "generation": e.GetSerial(),
				"class": class, "op": op.String(), "op_bits": int(op), "full_snapshot": full,
				"fields": fields, "field_types": types, "removed_fields": removed, "field_issues": issues}); err != nil {
				return err
			}
		}
		if op.Flag(manta.EntityOpDeleted) {
			delete(states, key)
		} else {
			states[key] = current
		}
		if class == "CDOTAGamerulesProxy" && (full || len(fields) > 0) {
			clock := map[string]interface{}{}
			for k, v := range current.fields {
				if strings.Contains(k, "Time") || strings.Contains(k, "Pause") || strings.Contains(k, "Tick") || strings.Contains(k, "GameState") {
					clock[k] = v
				}
			}
			if err := w.emit("clock", map[string]interface{}{"fields": clock, "source_entity_index": e.GetIndex(), "source_generation": e.GetSerial()}); err != nil {
				return err
			}
		}
		if class == "CDOTA_PlayerResource" {
			mappings = selectedHeroHandles(raw)
		}
		if class == "CDOTA_PlayerResource" || strings.HasPrefix(class, heroPrefix) && (op.Flag(manta.EntityOpCreated) || op.Flag(manta.EntityOpDeleted)) {
			return emitMappings()
		}
		return nil
	})
	p.Callbacks.OnCNETMsg_Tick(func(m *dota.CNETMsg_Tick) error { return w.message("net_tick", m) })
	p.Callbacks.OnCSVCMsg_ServerInfo(func(m *dota.CSVCMsg_ServerInfo) error { return w.message("server_info", m) })
	p.Callbacks.OnCDemoFileHeader(func(m *dota.CDemoFileHeader) error { return w.message("file_header", m) })
	p.Callbacks.OnCDemoFileInfo(func(m *dota.CDemoFileInfo) error { return w.message("file_info", m) })
	p.Callbacks.OnCMsgDOTACombatLogEntry(func(m *dota.CMsgDOTACombatLogEntry) error { return w.combatMessage(m) })
	p.Callbacks.OnCDOTAUserMsg_CombatLogBulkData(func(m *dota.CDOTAUserMsg_CombatLogBulkData) error { return w.message("combat_bulk", m) })
	p.OnModifierTableEntry(func(m *dota.CDOTAModifierBuffTableEntry) error { return w.message("modifier", m) })
	p.Callbacks.OnCMsgSource1LegacyGameEventList(func(m *dota.CMsgSource1LegacyGameEventList) error { return w.message("game_event_schema", m) })
	p.Callbacks.OnCMsgSource1LegacyGameEvent(func(m *dota.CMsgSource1LegacyGameEvent) error { return w.message("game_event", m) })
	p.Callbacks.OnCDemoStringTables(func(m *dota.CDemoStringTables) error {
		for _, table := range m.GetTables() {
			name := table.GetTableName()
			if name == "CombatLogNames" || name == "EntityNames" || name == "ModifierNames" {
				if err := w.message("string_table", table); err != nil {
					return err
				}
			}
		}
		return nil
	})
	if err = p.Start(); err != nil {
		_ = b.Flush()
		return err
	}
	if err = w.emit("trace_end", map[string]interface{}{"parser_completed": true, "game_build": p.GameBuild,
		"counts": w.counts, "validation": "unverified"}); err != nil {
		return err
	}
	return b.Flush()
}
