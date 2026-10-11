package main

import (
	"bytes"
	"encoding/json"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/proto"
	"testing"
)

func TestProjectileReferencesExcludePoolHandle(t *testing.T) {
	m := &dota.CDOTAUserMsg_TE_Projectile{Source: proto.Uint32(0), Target: proto.Uint32(123), Ability: proto.Uint32(44), Handle: proto.Int32(123), TargetProjectileHandle: proto.Int32(42)}
	r := projectileReferences(m)
	if len(r) != 3 || r["source"] != 0 || r["target"] != 123 || r["ability"] != 44 {
		t.Fatalf("unexpected refs %v", r)
	}
	if len(projectileReferences(&dota.CDOTAUserMsg_TE_DestroyProjectile{Handle: proto.Int32(123)})) != 0 {
		t.Fatal("pool handle treated as entity")
	}
}
func TestProjectileOptionalMissingAndExplicitZero(t *testing.T) {
	p := &manta.Parser{}
	buf := &bytes.Buffer{}
	w := &projectileWriter{p: p, context: newOrderContext(p), enc: json.NewEncoder(buf), counts: map[string]uint64{}}
	m := &dota.CDOTAUserMsg_CreateLinearProjectile{Handle: proto.Int32(0), StickyFowReveal: proto.Bool(false), Distance: proto.Float32(0)}
	if err := w.message(m); err != nil {
		t.Fatal(err)
	}
	var row map[string]interface{}
	if err := json.Unmarshal(buf.Bytes(), &row); err != nil {
		t.Fatal(err)
	}
	d := row["data"].(map[string]interface{})
	if d["handle"] != float64(0) || d["sticky_fow_reveal"] != false || d["distance"] != float64(0) {
		t.Fatalf("presence lost: %v", d)
	}
	if _, exists := d["velocity"]; exists {
		t.Fatal("missing velocity invented")
	}
	if row["damage"] != nil || row["impact_time"] != nil || row["screen_cue"] != nil {
		t.Fatal("gameplay evidence invented")
	}
}
func TestProjectileNegativeEntityReferenceRemainsAbsent(t *testing.T) {
	if len(projectileReferences(&dota.CDOTAUserMsg_CreateLinearProjectile{Entindex: proto.Int32(-1)})) != 0 {
		t.Fatal("negative entity index invented")
	}
}
