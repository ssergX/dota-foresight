package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"strings"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
)

const (
	tickRate      = 30.0
	cellWidth     = 128.0
	mapHalf       = 16384.0
	invalidHandle = 16777215
	heroPrefix    = "CDOTA_Unit_Hero_"
)

func f64(m map[string]interface{}, k string) (float64, bool) {
	v, ok := m[k]
	if !ok {
		return 0, false
	}
	switch x := v.(type) {
	case float32:
		return float64(x), true
	case float64:
		return x, true
	case int32:
		return float64(x), true
	case int64:
		return float64(x), true
	case uint32:
		return float64(x), true
	case uint64:
		return float64(x), true
	default:
		return 0, false
	}
}

type unitOut struct {
	Slot  int     `json:"slot"`
	X     float64 `json:"x"`
	Y     float64 `json:"y"`
	HP    int     `json:"hp"`
	MaxHP int     `json:"max_hp"`
	Mana  float64 `json:"mana"`
	Level int     `json:"level"`
	XP    int     `json:"xp"`
	Alive bool    `json:"alive"`
}

type stateLine struct {
	T     string    `json:"t"`
	Time  int       `json:"time"`
	Units []unitOut `json:"units"`
}

type heroMeta struct {
	Slot int    `json:"slot"`
	Team int    `json:"team"`
	Hero string `json:"hero"`
}

type wardOut struct {
	T    string  `json:"t"`
	ID   int     `json:"id"`
	Time int     `json:"time"`
	Kind string  `json:"kind"`
	Team int     `json:"team"`
	X    float64 `json:"x"`
	Y    float64 `json:"y"`
	Op   string  `json:"op"`
}

type metaLine struct {
	T         string     `json:"t"`
	GameStart float64    `json:"game_start_time"`
	TickRate  float64    `json:"tick_rate"`
	Heroes    []heroMeta `json:"heroes"`
}

func main() {
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

	var curTick int
	var gameStart float64
	heroes := map[int]heroMeta{}
	state := map[int]unitOut{}
	lastEmit := math.MinInt32
	var frames []stateLine
	var wards []wardOut

	p.Callbacks.OnCNETMsg_Tick(func(t *dota.CNETMsg_Tick) error {
		curTick = int(t.GetTick())
		return nil
	})

	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		cn := e.GetClassName()
		if cn == "CDOTAGamerulesProxy" {
			if v, ok := f64(e.Map(), "m_pGameRules.m_flGameStartTime"); ok && v > 0 {
				gameStart = v
			}
			return nil
		}
		if cn == "CDOTA_NPC_Observer_Ward" || cn == "CDOTA_NPC_Observer_Ward_TrueSight" {
			if gameStart <= 0 {
				return nil
			}
			gt := float64(curTick)/tickRate - gameStart
			if gt < 0 {
				return nil
			}
			var wop string
			if op&manta.EntityOpCreated != 0 {
				wop = "placed"
			} else if op&manta.EntityOpDeleted != 0 {
				wop = "gone"
			} else {
				return nil
			}
			m := e.Map()
			cx, _ := f64(m, "CBodyComponent.m_cellX")
			cy, _ := f64(m, "CBodyComponent.m_cellY")
			vx, _ := f64(m, "CBodyComponent.m_vecX")
			vy, _ := f64(m, "CBodyComponent.m_vecY")
			team, _ := f64(m, "m_iTeamNum")
			kind := "obs"
			if strings.Contains(cn, "TrueSight") {
				kind = "sentry"
			}
			wards = append(wards, wardOut{
				T: "ward", ID: int(e.GetIndex()), Time: int(math.Floor(gt)), Kind: kind,
				Team: int(team), X: cx*cellWidth + vx - mapHalf, Y: cy*cellWidth + vy - mapHalf, Op: wop,
			})
			return nil
		}
		if len(cn) < len(heroPrefix) || cn[:len(heroPrefix)] != heroPrefix {
			return nil
		}
		m := e.Map()
		if repl, ok := f64(m, "m_hReplicatingOtherHeroModel"); ok && int(repl) != invalidHandle {
			return nil // иллюзия
		}
		pidF, ok := f64(m, "m_iPlayerID")
		if !ok {
			return nil
		}
		slot := int(pidF) / 2 // m_iPlayerID = 2×индекс игрока -> слот 0..9
		if slot < 0 || slot > 9 {
			return nil
		}
		cellX, _ := f64(m, "CBodyComponent.m_cellX")
		cellY, _ := f64(m, "CBodyComponent.m_cellY")
		vecX, _ := f64(m, "CBodyComponent.m_vecX")
		vecY, _ := f64(m, "CBodyComponent.m_vecY")
		hp, _ := f64(m, "m_iHealth")
		maxHP, _ := f64(m, "m_iMaxHealth")
		mana, _ := f64(m, "m_flMana")
		lvl, _ := f64(m, "m_iCurrentLevel")
		xp, _ := f64(m, "m_iCurrentXP")
		life, _ := f64(m, "m_lifeState")
		team, _ := f64(m, "m_iTeamNum")
		heroes[slot] = heroMeta{Slot: slot, Team: int(team), Hero: cn}
		state[slot] = unitOut{
			Slot: slot, X: cellX*cellWidth + vecX - mapHalf, Y: cellY*cellWidth + vecY - mapHalf,
			HP: int(hp), MaxHP: int(maxHP), Mana: mana, Level: int(lvl), XP: int(xp), Alive: int(life) == 0,
		}

		if gameStart <= 0 {
			return nil
		}
		gt := float64(curTick)/tickRate - gameStart
		if gt < 0 || len(state) < 10 {
			return nil
		}
		sec := int(math.Floor(gt))
		if sec <= lastEmit {
			return nil
		}
		lastEmit = sec
		units := make([]unitOut, 0, 10)
		for s := 0; s < 10; s++ {
			if u, ok := state[s]; ok {
				units = append(units, u)
			}
		}
		frames = append(frames, stateLine{T: "state", Time: sec, Units: units})
		return nil
	})

	if err := p.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "parse:", err)
		os.Exit(1)
	}

	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	enc := json.NewEncoder(w)

	hs := make([]heroMeta, 0, 10)
	for s := 0; s < 10; s++ {
		if h, ok := heroes[s]; ok {
			hs = append(hs, h)
		}
	}
	if err := enc.Encode(metaLine{T: "meta", GameStart: gameStart, TickRate: tickRate, Heroes: hs}); err != nil {
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
