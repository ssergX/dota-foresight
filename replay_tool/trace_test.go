package main

import (
	"bytes"
	"encoding/json"
	"math"
	"reflect"
	"testing"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
)

func TestResourceMappingUsesExactHandleAndNotPlayerIDDivision(t *testing.T) {
	raw := map[string]interface{}{
		"m_iPlayerID": uint32(18),
		"m_vecPlayerTeamData.0009.m_hSelectedHero": uint64(123456789),
		"m_vecPlayerTeamData.0001.m_hSelectedHero": uint32(0),
		"m_vecPlayerTeamData.0002.m_hSelectedHero": int32(-1),
		"m_vecPlayerTeamData.bad.m_hSelectedHero":  uint32(100),
		"m_vecPlayerData.0003.m_hSelectedHero":     uint32(100),
	}
	want := map[int]uint64{9: 123456789, 1: 0}
	if got := selectedHeroHandles(raw); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestTraceDeltaKeepsZeroNullRemovalAndLargeIDsDistinct(t *testing.T) {
	previous, _ := projectTrace("CDOTA_PlayerResource", map[string]interface{}{"hp": int32(5), "old": true})
	current, issues := projectTrace("CDOTA_PlayerResource", map[string]interface{}{"hp": int32(0), "mana": nil, "id": uint64(76561198140280423), "bad": math.NaN()})
	fields, types, removed := traceDelta(previous, current, false)
	if fields["hp"] != int32(0) || fields["id"] != "76561198140280423" || types["id"] != "uint64" {
		t.Fatal(fields, types)
	}
	if v, ok := fields["mana"]; !ok || v != nil {
		t.Fatal("explicit unknown lost")
	}
	if !reflect.DeepEqual(removed, []string{"old"}) || len(issues) != 1 {
		t.Fatal(removed, issues)
	}
	if _, err := json.Marshal(fields); err != nil {
		t.Fatal(err)
	}
	f, _, r := traceDelta(current, current, false)
	if len(f) != 0 || len(r) != 0 {
		t.Fatal("unchanged state emitted")
	}
}

func TestTraceProjectionPreservesDecisionFieldsAndFiltersCosmetics(t *testing.T) {
	for _, key := range []string{"m_hItems.0000", "m_hAbilities.0002", "m_iTaggedAsVisibleByTeam", "m_nUnitState", "m_flMana", "CBodyComponent.m_cellX", "m_hOwnerEntity"} {
		if !traceField("CDOTA_Unit_Hero_Axe", key) {
			t.Fatal("required raw field omitted", key)
		}
	}
	if traceField("CDOTA_Unit_Hero_Axe", "m_nSkin") {
		t.Fatal("cosmetics retained")
	}
	if traceClass("CParticleSystem") {
		t.Fatal("particle classes retained")
	}
}

func TestTraceClockNeverInventsGameSecondsAndOrderIsExplicit(t *testing.T) {
	var output bytes.Buffer
	p := &manta.Parser{Tick: 17, NetTick: 1000}
	w := &traceWriter{p: p, enc: json.NewEncoder(&output), counts: map[string]uint64{}}
	for i := 0; i < 2; i++ {
		if err := w.emit("test", map[string]interface{}{}); err != nil {
			t.Fatal(err)
		}
	}
	p.Tick = 18
	if err := w.emit("test", map[string]interface{}{}); err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(&output)
	for i, wantSeq := range []float64{1, 2, 1} {
		var row map[string]interface{}
		if err := dec.Decode(&row); err != nil {
			t.Fatal(err)
		}
		if row["game_time"] != nil || row["record_index"] != float64(i+1) || row["sequence_in_tick"] != wantSeq {
			t.Fatal(row)
		}
	}
}

func TestCombatProtoPreservesAbsentVersusExplicitZero(t *testing.T) {
	var output bytes.Buffer
	w := &traceWriter{p: &manta.Parser{}, enc: json.NewEncoder(&output), counts: map[string]uint64{}}
	zero := uint32(0)
	if err := w.message("combat_log", &dota.CMsgDOTACombatLogEntry{Value: &zero}); err != nil {
		t.Fatal(err)
	}
	var row struct {
		Data map[string]interface{} `json:"data"`
	}
	if err := json.Unmarshal(output.Bytes(), &row); err != nil {
		t.Fatal(err)
	}
	if v, present := row.Data["value"]; !present || v != float64(0) {
		t.Fatal("known zero omitted")
	}
	if _, present := row.Data["timestamp"]; present {
		t.Fatal("absent timestamp invented")
	}
}
