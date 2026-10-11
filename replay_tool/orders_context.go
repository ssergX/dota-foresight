package main

import (
	"fmt"
	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
	"google.golang.org/protobuf/proto"
	"sort"
	"strings"
)

const ordersContextSchema = "replay-orders-context.v1"
const orderLinkProjection = "raw_ability_id_index_matches_only_not_inventory_census"

type orderContext struct {
	p         *manta.Parser
	resources map[int32]*manta.Entity
	live      map[int32]int32
}

func newOrderContext(p *manta.Parser) *orderContext {
	return &orderContext{p: p, resources: map[int32]*manta.Entity{}, live: map[int32]int32{}}
}
func (c *orderContext) update(e *manta.Entity, op manta.EntityOp) error {
	if op&manta.EntityOpDeleted != 0 {
		if c.live[e.GetIndex()] == e.GetSerial() {
			delete(c.live, e.GetIndex())
			delete(c.resources, e.GetIndex())
		}
		return nil
	}
	c.live[e.GetIndex()] = e.GetSerial()
	if e.GetClassName() == "CDOTA_PlayerResource" {
		c.resources[e.GetIndex()] = e
	}
	return nil
}
func entityReceipt(e *manta.Entity) map[string]interface{} {
	return map[string]interface{}{"entity_index": e.GetIndex(), "generation": e.GetSerial(), "class_name": e.GetClassName()}
}
func (c *orderContext) find(index int32) *manta.Entity {
	e := c.p.FindEntity(index)
	if e == nil {
		return nil
	}
	serial, ok := c.live[index]
	if !ok || serial != e.GetSerial() {
		return nil
	}
	return e
}
func (c *orderContext) handle(handle uint64) *manta.Entity {
	e := c.find(int32(handle & 16383))
	if e == nil || uint64(e.GetSerial()) != handle>>14 {
		return nil
	}
	return e
}
func rawUnsigned(v interface{}) (uint64, bool) {
	switch n := v.(type) {
	case uint64:
		return n, true
	case uint32:
		return uint64(n), true
	case int32:
		if n >= 0 {
			return uint64(n), true
		}
	}
	return 0, false
}
func (c *orderContext) links(hero *manta.Entity, abilityIndex *int32) []map[string]interface{} {
	out := []map[string]interface{}{}
	if abilityIndex == nil || *abilityIndex < 0 || *abilityIndex > 16383 {
		return out
	}
	for _, spec := range []struct {
		prefix string
		count  int
	}{{"m_hItems", 19}, {"m_vecAbilities", 32}, {"m_hAbilities", 32}} {
		for i := 0; i < spec.count; i++ {
			key := fmt.Sprintf("%s.%04d", spec.prefix, i)
			h, ok := rawUnsigned(hero.Get(key))
			if !ok || int32(h&16383) != *abilityIndex {
				continue
			}
			link := map[string]interface{}{"property": key, "raw_handle": h, "entity": nil}
			if e := c.handle(h); e != nil {
				link["entity"] = entityReceipt(e)
			}
			out = append(out, link)
		}
	}
	return out
}
func (c *orderContext) snapshot(message proto.Message) map[string]interface{} {
	out := map[string]interface{}{"field_entities": map[string]interface{}{}, "selected_heroes": []map[string]interface{}{}, "semantics": "raw_index_candidate_and_exact_handle_links_only"}
	m, ok := message.(*dota.CDOTAUserMsg_SpectatorPlayerUnitOrders)
	if !ok {
		return out
	}
	refs := out["field_entities"].(map[string]interface{})
	indices := map[int32]bool{}
	add := func(key string, index int32) {
		refs[key] = nil
		if e := c.find(index); e != nil {
			refs[key] = entityReceipt(e)
			indices[index] = true
		}
	}
	if m.Entindex != nil {
		add("entindex", *m.Entindex)
	}
	if m.AbilityId != nil {
		add("ability_id", *m.AbilityId)
	}
	if m.TargetIndex != nil {
		add("target_index", *m.TargetIndex)
	}
	for i, index := range m.Units {
		add(fmt.Sprintf("units.%d", i), index)
	}
	selected := []map[string]interface{}{}
	resourceIndices := []int{}
	for index := range c.resources {
		resourceIndices = append(resourceIndices, int(index))
	}
	sort.Ints(resourceIndices)
	for _, index := range resourceIndices {
		resource := c.resources[int32(index)]
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
			selected = append(selected, map[string]interface{}{"resource": entityReceipt(resource), "resource_slot": slot, "selected_handle": h, "selected_property": key, "steam_id": steam, "steam_property": steamKey, "hero": entityReceipt(hero), "links": c.links(hero, m.AbilityId)})
		}
	}
	out["selected_heroes"] = selected
	return out
}
