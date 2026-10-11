package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"math"
	"os"
	"strings"
)

const (
	tickRate      = 30.0
	cellWidth     = 128.0
	mapHalf       = 16384.0
	invalidHandle = 16777215
	heroPrefix    = "CDOTA_Unit_Hero_"
)

// Missing properties are unknown; a present zero remains a known zero.
func f64(m map[string]interface{}, k string) (float64, bool) {
	v, ok := m[k]
	if !ok {
		return 0, false
	}
	var n float64
	switch x := v.(type) {
	case float32:
		n = float64(x)
	case float64:
		n = x
	case int32:
		n = float64(x)
	case int64:
		n = float64(x)
	case uint32:
		n = float64(x)
	case uint64:
		n = float64(x)
	default:
		return 0, false
	}
	return n, !math.IsNaN(n) && !math.IsInf(n, 0)
}
func number(m map[string]interface{}, k string) *float64 {
	v, ok := f64(m, k)
	if !ok {
		return nil
	}
	return &v
}
func integer(m map[string]interface{}, k string) *int {
	v, ok := f64(m, k)
	if !ok || math.Trunc(v) != v {
		return nil
	}
	n := int(v)
	return &n
}
func coordinate(m map[string]interface{}, cell, vec string) *float64 {
	c, cok := f64(m, cell)
	v, vok := f64(m, vec)
	if !cok || !vok {
		return nil
	}
	n := c*cellWidth + v - mapHalf
	return &n
}

type unitOut struct {
	Slot        int      `json:"slot"`
	EntityIndex int      `json:"entity_index"`
	Generation  int      `json:"generation"`
	X           *float64 `json:"x"`
	Y           *float64 `json:"y"`
	HP          *int     `json:"hp"`
	MaxHP       *int     `json:"max_hp"`
	Mana        *float64 `json:"mana"`
	Level       *int     `json:"level"`
	XP          *int     `json:"xp"`
	Alive       *bool    `json:"alive"`
}
type stateLine struct {
	T        string    `json:"t"`
	Time     float64   `json:"time"`
	Tick     int       `json:"tick"`
	Sequence int       `json:"sequence"`
	Units    []unitOut `json:"units"`
}
type heroMeta struct {
	Slot int    `json:"slot"`
	Team *int   `json:"team"`
	Hero string `json:"hero"`
}
type wardOut struct {
	T          string   `json:"t"`
	ID         int      `json:"id"`
	Generation int      `json:"generation"`
	Time       float64  `json:"time"`
	Tick       int      `json:"tick"`
	Sequence   int      `json:"sequence"`
	Kind       string   `json:"kind"`
	Team       *int     `json:"team"`
	X          *float64 `json:"x"`
	Y          *float64 `json:"y"`
	Op         string   `json:"op"`
}
type capability struct {
	ID             string `json:"capability_id"`
	Implementation string `json:"implementation"`
	Validation     string `json:"validation"`
}
type metaLine struct {
	T            string       `json:"t"`
	Schema       string       `json:"schema_version"`
	Extractor    string       `json:"extractor_name"`
	Version      string       `json:"extractor_version"`
	Timebase     string       `json:"timebase_version"`
	Completeness string       `json:"completeness"`
	Warnings     []string     `json:"parse_warnings"`
	Capabilities []capability `json:"capabilities"`
	GameStart    float64      `json:"game_start_time"`
	TickRate     float64      `json:"tick_rate"`
	Heroes       []heroMeta   `json:"heroes"`
}

func main() {
	if len(os.Args) == 3 && os.Args[1] == "--projectiles" {
		if err := runProjectiles(os.Args[2], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "projectiles:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 3 && os.Args[1] == "--orders-context" {
		if err := runOrdersMode(os.Args[2], os.Stdout, true); err != nil {
			fmt.Fprintln(os.Stderr, "orders context:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 3 && os.Args[1] == "--orders" {
		if err := runOrders(os.Args[2], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "orders:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 3 && os.Args[1] == "--combat-names" {
		if err := runCombatNames(os.Args[2], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "combat names:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) == 3 && os.Args[1] == "--trace" {
		if err := runTrace(os.Args[2], os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "trace:", err)
			os.Exit(1)
		}
		return
	}
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: replay_tool <path.dem>")
		os.Exit(2)
	}
	f, err := os.Open(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer f.Close()
	p, err := manta.NewStreamParser(f)
	if err != nil {
		fmt.Fprintln(os.Stderr, "parser:", err)
		os.Exit(1)
	}
	var curTick, sequence int
	var gameStart *float64
	heroes := map[int]heroMeta{}
	state := map[int]unitOut{}
	heroEntities := map[int]int{}
	selectedHandles := map[int]uint64{}
	heroGenerations := map[int]int{}
	slotEntities := map[int]int{}
	lastEmit := math.MinInt32
	var frames []stateLine
	var wards []wardOut
	generation := map[int]int{}
	activeWards := map[int]wardOut{}
	warnings := []string{"resource_slot_provider_mapping_unverified", "unverified_tick30_clock_pause_mapping", "sampled_world_state_not_visibility", "game_start_mapping_not_prefix_verified", "game_build_and_patch_unavailable"}
	// Snapshot after all entity updates of a tick, when the next tick begins.
	emit := func() {
		if gameStart == nil || len(state) == 0 {
			return
		}
		gt := float64(curTick)/tickRate - *gameStart
		sec := int(math.Floor(gt))
		if sec <= lastEmit {
			return
		}
		lastEmit = sec
		units := make([]unitOut, 0, len(state))
		for s := 0; s < 10; s++ {
			if u, ok := state[s]; ok {
				units = append(units, u)
			}
		}
		frames = append(frames, stateLine{T: "state", Time: gt, Tick: curTick, Sequence: sequence + 1, Units: units})
	}
	p.Callbacks.OnCNETMsg_Tick(func(t *dota.CNETMsg_Tick) error {
		next := int(t.GetTick())
		if next != curTick {
			emit()
			sequence = 0
		}
		curTick = next
		return nil
	})
	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		sequence++
		cn := e.GetClassName()
		m := e.Map()
		if cn == "CDOTA_PlayerResource" {
			selectedHandles = selectedHeroHandles(m)
			return nil
		}
		if cn == "CDOTAGamerulesProxy" {
			if v, ok := f64(m, "m_pGameRules.m_flGameStartTime"); ok && v > 0 {
				gameStart = &v
			}
			return nil
		}
		if cn == "CDOTA_NPC_Observer_Ward" || cn == "CDOTA_NPC_Observer_Ward_TrueSight" {
			id := int(e.GetIndex())
			if op&manta.EntityOpCreated != 0 {
				generation[id]++
				kind := "obs"
				if strings.Contains(cn, "TrueSight") {
					kind = "sentry"
				}
				wd := wardOut{T: "ward", ID: id, Generation: generation[id], Tick: curTick, Sequence: sequence,
					Kind: kind, Team: integer(m, "m_iTeamNum"), X: coordinate(m, "CBodyComponent.m_cellX", "CBodyComponent.m_vecX"), Y: coordinate(m, "CBodyComponent.m_cellY", "CBodyComponent.m_vecY"), Op: "placed"}
				activeWards[id] = wd
				wards = append(wards, wd)
			} else if op&manta.EntityOpDeleted != 0 {
				if wd, ok := activeWards[id]; ok {
					wd.Tick = curTick
					wd.Sequence = sequence
					wd.Op = "gone"
					wards = append(wards, wd)
					delete(activeWards, id)
				} else {
					warnings = append(warnings, "ward_removal_without_observed_placement")
				}
			}
			return nil
		}
		if !strings.HasPrefix(cn, heroPrefix) {
			return nil
		}
		id := int(e.GetIndex())
		if op&manta.EntityOpDeleted != 0 {
			if s, ok := heroEntities[id]; ok {
				if slotEntities[s] == id {
					delete(state, s)
					delete(slotEntities, s)
				}
				delete(heroEntities, id)
			}
			return nil
		}
		// A raw m_iPlayerID may have a patch-dependent decoder. Join the
		// resource's selected entity handle including serial instead of /2.
		slot := -1
		for resourceSlot, handle := range selectedHandles {
			if selected := p.FindEntityByHandle(handle); selected != nil && selected.GetIndex() == e.GetIndex() && selected.GetSerial() == e.GetSerial() {
				slot = resourceSlot
				break
			}
		}
		if slot < 0 || slot > 9 {
			return nil
		}
		if op&manta.EntityOpCreated != 0 {
			heroGenerations[id]++
		}
		if previous, exists := slotEntities[slot]; exists && previous != id {
			warnings = append(warnings, "ambiguous_primary_hero_slot_collision")
		}
		slotEntities[slot] = id
		var alive *bool
		if life := integer(m, "m_lifeState"); life != nil {
			v := *life == 0
			alive = &v
		}
		heroes[slot] = heroMeta{Slot: slot, Team: integer(m, "m_iTeamNum"), Hero: cn}
		heroEntities[id] = slot
		state[slot] = unitOut{Slot: slot, EntityIndex: id, Generation: heroGenerations[id], X: coordinate(m, "CBodyComponent.m_cellX", "CBodyComponent.m_vecX"), Y: coordinate(m, "CBodyComponent.m_cellY", "CBodyComponent.m_vecY"),
			HP: integer(m, "m_iHealth"), MaxHP: integer(m, "m_iMaxHealth"), Mana: number(m, "m_flMana"), Level: integer(m, "m_iCurrentLevel"), XP: integer(m, "m_iCurrentXP"), Alive: alive}
		return nil
	})
	if err := p.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "parse:", err)
		os.Exit(1)
	}
	emit()
	if gameStart == nil {
		fmt.Fprintln(os.Stderr, "parse: game start mapping unavailable")
		os.Exit(1)
	}
	for i := range wards {
		wards[i].Time = float64(wards[i].Tick)/tickRate - *gameStart
	}
	if len(activeWards) > 0 {
		warnings = append(warnings, "ward_lifetimes_right_censored_at_replay_end")
	}
	hs := make([]heroMeta, 0, 10)
	for s := 0; s < 10; s++ {
		if h, ok := heroes[s]; ok {
			hs = append(hs, h)
		}
	}
	caps := []capability{}
	for _, id := range []string{"primary_hero_identity", "positions_resources", "game_clock", "ward_lifecycle"} {
		caps = append(caps, capability{id, "implemented", "unverified"})
	}
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	enc := json.NewEncoder(w)
	meta := metaLine{T: "meta", Schema: "replay-jsonl.v2", Extractor: "manta", Version: "foresight-replay/2", Timebase: "tick30-minus-start/unverified", Completeness: "partial", Warnings: warnings, Capabilities: caps, GameStart: *gameStart, TickRate: tickRate, Heroes: hs}
	if err := enc.Encode(meta); err != nil {
		fmt.Fprintln(os.Stderr, "encode meta:", err)
		os.Exit(1)
	}
	for _, fr := range frames {
		if err := enc.Encode(fr); err != nil {
			fmt.Fprintln(os.Stderr, "encode state:", err)
			os.Exit(1)
		}
	}
	for _, wd := range wards {
		if err := enc.Encode(wd); err != nil {
			fmt.Fprintln(os.Stderr, "encode ward:", err)
			os.Exit(1)
		}
	}
}
