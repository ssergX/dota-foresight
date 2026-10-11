package main

// Spectator order messages are observations of the replay's message stream.
// Their presence does not establish a client key press, an accepted command,
// ability commit, player identity, or the completeness of attempted actions.
import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

const ordersSchema = "replay-orders.v1"

var orderCallbacks = []string{
	"dota.CDOTAUserMsg_SpectatorPlayerUnitOrders",
	"dota.CDOTAUserMsg_QueuedOrderRemoved",
	"dota.CDOTAUserMsg_SpectatorPlayerClick",
	"dota.CDOTAUserMsg_HudError",
	"dota.CDemoUserCmd",
}

type orderWriter struct {
	p        *manta.Parser
	enc      *json.Encoder
	record   uint64
	tick     uint32
	sequence uint64
	counts   map[string]uint64
	context  *orderContext
}

func (w *orderWriter) emit(kind string, fields map[string]interface{}) error {
	if w.tick != w.p.Tick {
		w.tick, w.sequence = w.p.Tick, 0
	}
	w.record++
	w.sequence++
	fields["t"], fields["record_index"] = kind, w.record
	fields["demo_tick"], fields["net_tick"] = w.p.Tick, w.p.NetTick
	fields["sequence_in_tick"], fields["game_time"] = w.sequence, nil
	return w.enc.Encode(fields)
}

func (w *orderWriter) message(message proto.Message) error {
	data, err := (protojson.MarshalOptions{UseProtoNames: true}).Marshal(message)
	if err != nil {
		return err
	}
	name := string(message.ProtoReflect().Descriptor().FullName())
	fields := map[string]interface{}{
		"protobuf_type": name, "data": json.RawMessage(data),
		"validation":     "unverified_source_observation",
		"actor_identity": nil, "command_stage": nil,
		"protobuf_unknown_fields_hex": hex.EncodeToString(message.ProtoReflect().GetUnknown()),
	}
	if w.context != nil {
		fields["entity_context"] = w.context.snapshot(message)
	}
	// Enum spelling is a schema annotation; an unknown integer stays unknown.
	if order, ok := message.(*dota.CDOTAUserMsg_SpectatorPlayerUnitOrders); ok && order.OrderType != nil {
		if spelling, known := dota.DotaunitorderT_name[*order.OrderType]; known {
			fields["order_type_schema_name"] = spelling
		} else {
			fields["order_type_schema_name"] = nil
		}
	}
	if err = w.emit("order_message", fields); err != nil {
		return err
	}
	w.counts[name]++
	return nil
}

func orderMeta(replaySHA string, replayBytes int64) map[string]interface{} {
	return map[string]interface{}{
		"schema_version": ordersSchema, "extractor_name": "manta",
		"extractor_version": traceVersion, "manta_version": "v1.5.0",
		"replay_sha256": replaySHA, "replay_bytes": replayBytes,
		"source_callbacks":               orderCallbacks,
		"completeness":                   "registered_source_callback_census_only",
		"client_execute_orders_dispatch": "unavailable_in_manta_v1.5.0",
		"timebase_version":               "raw-demo-net-ticks.v1",
		"sequence_semantics":             "callback_stream_order_not_verified_simulation_order",
		"validation":                     "unverified_source_observation",
		"attempt_coverage":               nil, "accepted_commands": nil, "committed_commands": nil,
		"warnings": []string{
			"spectator_order_messages_do_not_establish_client_input_or_command_acceptance",
			"entity_indices_and_ability_id_are_raw_fields_without_generation_or_identity_join",
			"raw_ticks_do_not_establish_game_time_or_pause_mapping",
			"missing_messages_do_not_establish_absent_attempts",
			"hud_error_and_queue_removal_do_not_establish_rejection_without_validated_links",
		},
	}
}

// runOrders makes a compact independent pass, without emitting entity state.
// Only a terminal orders_end with parser_completed=true seals a full parse.
func runOrders(path string, output io.Writer) error {
	return runOrdersMode(path, output, false)
}

func runOrdersMode(path string, output io.Writer, contextual bool) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	replayBytes, err := io.Copy(h, f)
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
	defer b.Flush() // Preserve incomplete source observations on parser errors.
	counts := map[string]uint64{}
	for _, name := range orderCallbacks {
		counts[name] = 0
	}
	w := &orderWriter{p: p, enc: json.NewEncoder(b), counts: counts}
	if contextual {
		w.context = newOrderContext(p)
		p.OnEntity(w.context.update)
	}
	replaySHA := hex.EncodeToString(h.Sum(nil))
	meta := orderMeta(replaySHA, replayBytes)
	if contextual {
		meta["schema_version"] = ordersContextSchema
		meta["context_semantics"] = "same_callback_current_entity_snapshot_not_gameplay_identity"
		meta["link_projection"] = orderLinkProjection
	}
	if err = w.emit("meta", meta); err != nil {
		return err
	}
	p.Callbacks.OnCDOTAUserMsg_SpectatorPlayerUnitOrders(func(m *dota.CDOTAUserMsg_SpectatorPlayerUnitOrders) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_QueuedOrderRemoved(func(m *dota.CDOTAUserMsg_QueuedOrderRemoved) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_SpectatorPlayerClick(func(m *dota.CDOTAUserMsg_SpectatorPlayerClick) error { return w.message(m) })
	p.Callbacks.OnCDOTAUserMsg_HudError(func(m *dota.CDOTAUserMsg_HudError) error { return w.message(m) })
	p.Callbacks.OnCDemoUserCmd(func(m *dota.CDemoUserCmd) error { return w.message(m) })
	if err = p.Start(); err != nil {
		return err
	}
	availability := "source_order_messages_observed"
	if counts[orderCallbacks[0]] == 0 {
		availability = "no_spectator_unit_order_messages_observed"
	}
	schema := ordersSchema
	if contextual {
		schema = ordersContextSchema
	}
	footer := map[string]interface{}{
		"schema_version": schema, "replay_sha256": replaySHA,
		"extractor_name": "manta", "extractor_version": traceVersion, "manta_version": "v1.5.0",
		"replay_bytes": replayBytes, "parser_completed": true,
		"counts": counts, "message_count": w.record - 1,
		"game_build": p.GameBuild, "availability": availability,
		"validation":       "unverified_source_observation",
		"attempt_coverage": nil, "accepted_commands": nil, "committed_commands": nil,
	}
	if contextual {
		footer["link_projection"] = orderLinkProjection
	}
	if err = w.emit("orders_end", footer); err != nil {
		return err
	}
	return b.Flush()
}
