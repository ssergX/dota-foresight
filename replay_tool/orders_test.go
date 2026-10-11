package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/proto"
)

func decodeOrderRows(t *testing.T, b *bytes.Buffer) []map[string]interface{} {
	t.Helper()
	var rows []map[string]interface{}
	for _, line := range strings.Split(strings.TrimSpace(b.String()), "\n") {
		var row map[string]interface{}
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			t.Fatal(err)
		}
		rows = append(rows, row)
	}
	return rows
}

func TestOrderPresenceUnknownFieldsAndUnpromotedStage(t *testing.T) {
	b := new(bytes.Buffer)
	w := &orderWriter{p: &manta.Parser{Tick: 100, NetTick: 98}, enc: json.NewEncoder(b), counts: map[string]uint64{}}
	m := &dota.CDOTAUserMsg_SpectatorPlayerUnitOrders{
		Entindex: proto.Int32(0), OrderType: proto.Int32(8), Units: []int32{12, 22},
		AbilityId: proto.Int32(116), Queue: proto.Bool(false), SequenceNumber: proto.Int32(0),
	}
	m.ProtoReflect().SetUnknown([]byte{0xA0, 0x06, 0x01})
	if err := w.message(m); err != nil {
		t.Fatal(err)
	}
	rows := decodeOrderRows(t, b)
	r := rows[0]
	d := r["data"].(map[string]interface{})
	if d["entindex"] != float64(0) || d["queue"] != false || d["sequence_number"] != float64(0) {
		t.Fatalf("present zero lost: %v", d)
	}
	if _, exists := d["target_index"]; exists {
		t.Fatal("missing target fabricated")
	}
	if r["protobuf_type"] != orderCallbacks[0] || r["order_type_schema_name"] != "DOTA_UNIT_ORDER_CAST_NO_TARGET" {
		t.Fatal(r)
	}
	if r["protobuf_unknown_fields_hex"] != "a00601" {
		t.Fatal("unrecognized source bytes lost")
	}
	if r["command_stage"] != nil || r["actor_identity"] != nil || r["game_time"] != nil {
		t.Fatal("source observation promoted")
	}
	if r["demo_tick"] != float64(100) || r["net_tick"] != float64(98) || w.counts[orderCallbacks[0]] != 1 {
		t.Fatal(r)
	}
}

func TestOrderSequenceResetAndUnknownEnum(t *testing.T) {
	b := new(bytes.Buffer)
	w := &orderWriter{p: &manta.Parser{Tick: 1}, enc: json.NewEncoder(b), counts: map[string]uint64{}}
	if err := w.message(&dota.CDOTAUserMsg_SpectatorPlayerUnitOrders{OrderType: proto.Int32(999999)}); err != nil {
		t.Fatal(err)
	}
	if err := w.message(&dota.CDOTAUserMsg_QueuedOrderRemoved{UnitOrderSequence: []uint32{4, 0}}); err != nil {
		t.Fatal(err)
	}
	w.p.Tick = 3
	if err := w.message(&dota.CDOTAUserMsg_HudError{OrderId: proto.Int32(0)}); err != nil {
		t.Fatal(err)
	}
	r := decodeOrderRows(t, b)
	if r[0]["order_type_schema_name"] != nil || r[0]["data"].(map[string]interface{})["order_type"] != float64(999999) {
		t.Fatal(r[0])
	}
	for i, expected := range []float64{1, 2, 1} {
		if r[i]["sequence_in_tick"] != expected || r[i]["record_index"] != float64(i+1) {
			t.Fatal(r[i])
		}
	}
}

func TestOrderCensusMetadataDoesNotClaimClientInput(t *testing.T) {
	m := orderMeta(strings.Repeat("a", 64), 123)
	if m["replay_bytes"] != int64(123) || m["client_execute_orders_dispatch"] != "unavailable_in_manta_v1.5.0" {
		t.Fatal(m)
	}
	if m["attempt_coverage"] != nil || m["accepted_commands"] != nil || m["committed_commands"] != nil {
		t.Fatal("invented coverage")
	}
	if len(m["source_callbacks"].([]string)) != 5 {
		t.Fatal("incomplete declared census")
	}
}

type failedOrderOutput struct{}

func (failedOrderOutput) Write([]byte) (int, error) { return 0, errors.New("output unavailable") }

func TestOrderWriterReportsFailureWithoutIncrementingMessageCount(t *testing.T) {
	w := &orderWriter{p: &manta.Parser{}, enc: json.NewEncoder(failedOrderOutput{}), counts: map[string]uint64{}}
	if err := w.message(&dota.CDOTAUserMsg_HudError{}); err == nil {
		t.Fatal("write failure swallowed")
	}
	if w.counts[orderCallbacks[3]] != 0 {
		t.Fatal("unwritten message counted")
	}
}

func TestOrdersMissingReplayIsNotCompletedCensus(t *testing.T) {
	var b bytes.Buffer
	if err := runOrders(t.TempDir()+"/missing.dem", &b); err == nil || b.Len() != 0 {
		t.Fatal("missing replay produced completed census")
	}
}
