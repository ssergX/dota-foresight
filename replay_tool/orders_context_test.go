package main

import (
	"bytes"
	"encoding/json"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/proto"
	"testing"
)

func TestContextPreservesUnknownIndexAndNoCatalogInference(t *testing.T) {
	p := &manta.Parser{Tick: 10, NetTick: 9}
	b := new(bytes.Buffer)
	w := &orderWriter{p: p, enc: json.NewEncoder(b), counts: map[string]uint64{}, context: newOrderContext(p)}
	err := w.message(&dota.CDOTAUserMsg_SpectatorPlayerUnitOrders{AbilityId: proto.Int32(116), Units: []int32{42}, Entindex: proto.Int32(0)})
	if err != nil {
		t.Fatal(err)
	}
	row := decodeOrderRows(t, b)[0]
	ctx := row["entity_context"].(map[string]interface{})
	fields := ctx["field_entities"].(map[string]interface{})
	if len(fields) != 3 || fields["ability_id"] != nil || fields["units.0"] != nil || fields["entindex"] != nil {
		t.Fatal(fields)
	}
	if row["actor_identity"] != nil || row["command_stage"] != nil {
		t.Fatal("raw association promoted")
	}
}
func TestContextOtherCallbacksHaveNoEntityCandidates(t *testing.T) {
	c := newOrderContext(&manta.Parser{})
	ctx := c.snapshot(&dota.CDOTAUserMsg_HudError{OrderId: proto.Int32(42)})
	if len(ctx["field_entities"].(map[string]interface{})) != 0 {
		t.Fatal("HUD id treated as entity")
	}
}
func TestContextUnsignedPresenceDoesNotCoerceNegativeFloatOrBool(t *testing.T) {
	for _, v := range []interface{}{int32(-1), float64(2), true, nil} {
		if _, ok := rawUnsigned(v); ok {
			t.Fatalf("coerced raw handle %v", v)
		}
	}
	for _, v := range []interface{}{uint64(0), uint32(5), int32(9)} {
		if _, ok := rawUnsigned(v); !ok {
			t.Fatal(v)
		}
	}
}

func TestContextNoAbilityIdDoesNotInventoryCensus(t *testing.T) {
	c := newOrderContext(&manta.Parser{})
	// Returning before dereferencing an entity proves that absent/invalid IDs
	// never trigger an unrelated inventory or ability projection.
	for _, index := range []*int32{nil, proto.Int32(-1), proto.Int32(16384)} {
		if len(c.links(nil, index)) != 0 {
			t.Fatal("unrelated link projection")
		}
	}
}
