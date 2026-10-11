package main

import (
	"encoding/json"
	"math"
	"testing"
)

func TestMissingPropertyIsDifferentFromKnownZero(t *testing.T) {
	m := map[string]interface{}{"m_iHealth": int32(0), "m_flMana": float32(0)}
	if integer(m, "missing") != nil || number(m, "missing") != nil {
		t.Fatal("missing property became a value")
	}
	if hp := integer(m, "m_iHealth"); hp == nil || *hp != 0 {
		t.Fatal("known zero health was lost")
	}
	if mana := number(m, "m_flMana"); mana == nil || *mana != 0 {
		t.Fatal("known zero mana was lost")
	}
}

func TestInvalidNumbersDoNotBecomeFacts(t *testing.T) {
	for _, value := range []interface{}{nil, true, "0", math.NaN(), math.Inf(1)} {
		if _, ok := f64(map[string]interface{}{"x": value}, "x"); ok {
			t.Fatalf("accepted invalid value %v", value)
		}
	}
	if integer(map[string]interface{}{"x": float64(1.5)}, "x") != nil {
		t.Fatal("fractional integer was truncated")
	}
}

func TestCoordinateRequiresBothComponents(t *testing.T) {
	m := map[string]interface{}{"cell": uint32(128)}
	if coordinate(m, "cell", "vec") != nil {
		t.Fatal("missing vector became a coordinate")
	}
	m["vec"] = float32(0)
	value := coordinate(m, "cell", "vec")
	if value == nil || *value != 0 {
		t.Fatal("known zero coordinate lost")
	}
}

func TestUnknownResourcesAreSerializedAsNull(t *testing.T) {
	data, err := json.Marshal(unitOut{Slot: 0})
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]interface{}
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"x", "y", "hp", "max_hp", "mana", "level", "xp", "alive"} {
		value, present := fields[name]
		if !present || value != nil {
			t.Fatalf("unknown %s was omitted or guessed", name)
		}
	}
}
