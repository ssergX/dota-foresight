from dota_coach.minimap import MAP_MAX, MAP_MIN, MARGIN, SIZE, TOPBAR, world_to_px


def test_center_maps_to_field_center():
    assert world_to_px(0.0, 0.0) == (MARGIN + SIZE // 2, TOPBAR + SIZE // 2)


def test_west_north_is_top_left():
    # x=MIN (запад), y=MAX (север) -> левый верхний угол поля
    assert world_to_px(MAP_MIN, MAP_MAX) == (MARGIN, TOPBAR)


def test_east_south_is_bottom_right():
    assert world_to_px(MAP_MAX, MAP_MIN) == (MARGIN + SIZE, TOPBAR + SIZE)


def test_out_of_range_is_clamped():
    assert world_to_px(1e9, -1e9) == (MARGIN + SIZE, TOPBAR + SIZE)
    assert world_to_px(-1e9, 1e9) == (MARGIN, TOPBAR)
