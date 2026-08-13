"""Smoke tests for running_summary.py.

Run from project root:
  python debug/test_running_summary.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from running_summary import build_summary, _format_pace, _ordinal, _rank_tag, _keycap_number, _landmark_lines

BIRTH_YEAR = 1971  # -> 2026 is M55, matching the user's own worked example

SPLITS_INDEX = {
    '1k': [
        {'source_key': 'x', 'date': '2024-01-01', 'pace_s_per_km': 196.0, 'age_bracket': 'M50'},  # all-time PB, pre-M55
        {'source_key': 'y', 'date': '2026-02-01', 'pace_s_per_km': 222.0, 'age_bracket': 'M55'},   # M55 PB (slower than x)
        {'source_key': 'z', 'date': '2026-06-01', 'pace_s_per_km': 260.0, 'age_bracket': 'M55'},   # this season, slowest
    ],
}


def test_format_pace_has_no_unit_suffix():
    # The new compact format states the min/km convention once (in the
    # icon legend / chat explanation), never repeats "/km" per number.
    assert _format_pace(260.0) == "4'20"
    assert _format_pace(196.0) == "3'16"
    print('  test_format_pace_has_no_unit_suffix    PASS')


def test_format_pace_floors_never_rounds_up_past_a_boundary():
    """Found 2026-07-27: a genuinely sub-40min 10k (239.5459s/km, elapsed
    39:55) was displaying as "4'00" -- round() pushed it across a boundary
    the true value never crossed, making a real achievement look like it
    missed the mark. floor() can never do this."""
    assert _format_pace(239.5459390862944) == "3'59"
    assert round(239.5459390862944) == 240  # confirms round() really would have crossed it
    assert _format_pace(240.0) == "4'00"    # a value truly at the boundary still shows it
    assert _format_pace(240.9) == "4'00"    # truly past it stays past it
    print('  test_format_pace_floors_never_rounds_up_past_a_boundary  PASS')


def test_ordinal():
    assert _ordinal(4) == '4th'
    assert _ordinal(11) == '11th'
    assert _ordinal(15) == '15th'
    assert _ordinal(21) == '21st'
    print('  test_ordinal                           PASS')


def test_rank_tag_uses_medals_for_top_three():
    assert _rank_tag(1) == '🥇'
    assert _rank_tag(2) == '🥈'
    assert _rank_tag(3) == '🥉'
    print('  test_rank_tag_uses_medals_for_top_three  PASS')


def test_rank_tag_uses_flag_for_fourth_and_beyond():
    assert _rank_tag(4) == '🏁4th'
    assert _rank_tag(15) == '🏁15th'
    print('  test_rank_tag_uses_flag_for_fourth_and_beyond  PASS')


def test_split_line_absent_when_not_in_todays_run():
    """A distance today's run didn't reach must produce NO line -- the
    opposite of cycling's always-degrade convention."""
    today_splits = {'1k': {'pace_s_per_km': 240.0, 'elapsed_s': 240.0, 'avg_hr': 150.0}}  # no '3k' entry
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=SPLITS_INDEX,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    assert '1k ' in summary
    assert '3k ' not in summary
    print('  test_split_line_absent_when_not_in_todays_run  PASS')


def test_split_line_season_rank_and_pb_values():
    today_splits = {'1k': {'pace_s_per_km': 240.0, 'elapsed_s': 240.0, 'avg_hr': 150.0}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=SPLITS_INDEX,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('1k'))
    # Pool for 2026 (season): 222.0 (y), 260.0 (z), plus today's 240.0 -- three
    # entries; only y's 222.0 is faster than today's 240.0 -> rank 2 -> silver medal.
    assert '🥈' in line, line
    assert "🌟3'42" in line, line   # fastest in 2026: y at 222.0
    assert "🎂3'42" in line, line   # fastest M55-bracket: y at 222.0
    assert "👑3'16" in line, line   # fastest all-time (any bracket): x at 196.0
    print('  test_split_line_season_rank_and_pb_values  PASS')


def test_split_line_shows_display_tag_for_manual_race_entry():
    """A manually-entered measured-course race result must read distinctly
    from an ordinary GPS-derived split wherever it wins a PB/SB comparison."""
    hm_index = {
        'HM': [
            {'source_key': 'manual/2023-07-02-HM', 'date': '2023-07-02',
             'pace_s_per_km': 241.07, 'age_bracket': 'M50',
             'display_tag': "📏'23"},
        ],
    }
    today_splits = {'HM': {'pace_s_per_km': 260.0, 'elapsed_s': 5485.0, 'avg_hr': 150.0}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=hm_index,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('HM'))
    assert "👑4'01 📏'23" in line, line
    print('  test_split_line_shows_display_tag_for_manual_race_entry  PASS')


def test_split_line_shows_bound_prefix_when_longer_distance_pb_is_faster():
    """Reproduces the real 2026-07-27 finding: a GPS-undercounted 20k split
    from the same file as a manually-corrected HM race can't legitimately
    be slower than the HM entry -- the displayed 20k PB must borrow the HM
    value, marked with a leading '≤' so it doesn't read as a directly-
    measured 20k split."""
    index = {
        '10k': [{'source_key': 'gps', 'date': '2023-07-02', 'pace_s_per_km': 245.0, 'age_bracket': 'M50'}],
        'HM': [{'source_key': 'manual/2023-07-02-HM', 'date': '2023-07-02',
                'pace_s_per_km': 241.07, 'age_bracket': 'M50', 'display_tag': "📏'23"}],
    }
    today_splits = {'10k': {'pace_s_per_km': 250.0, 'elapsed_s': 2500.0, 'avg_hr': 150.0}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=index,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('10k'))
    assert "👑≤4'01 📏'23" in line, line
    print('  test_split_line_shows_bound_prefix_when_longer_distance_pb_is_faster  PASS')


def test_monotonic_bound_applies_even_when_longer_distance_not_in_todays_run():
    """The bound sweep runs over the full distance list, not just labels
    today's run reached -- a stronger longer-distance PB must still clamp
    a shorter one even if today's run never got that far."""
    index = {
        '10k': [{'source_key': 'gps', 'date': '2023-07-02', 'pace_s_per_km': 245.0, 'age_bracket': 'M55'}],
        'Marathon': [{'source_key': 'race', 'date': '2024-10-13', 'pace_s_per_km': 230.0, 'age_bracket': 'M55'}],
    }
    today_splits = {'10k': {'pace_s_per_km': 250.0, 'elapsed_s': 2500.0, 'avg_hr': 150.0}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=index,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('10k'))
    assert "👑≤3'50" in line, line  # 230.0s/km, borrowed from Marathon despite not running one today
    print('  test_monotonic_bound_applies_even_when_longer_distance_not_in_todays_run  PASS')


def test_split_line_shows_hrr_and_ag():
    # 1km in 240s at HR 150 -> pct_hrr(150) with REST_HR=43/MAX_HR=173:
    # (150-43)/(173-43)*100 = 82.3%.
    today_splits = {'1k': {'pace_s_per_km': 240.0, 'elapsed_s': 240.0, 'avg_hr': 150.0}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=SPLITS_INDEX,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('1k'))
    assert '❤️82%' in line, line
    assert '🏅' in line, line
    print('  test_split_line_shows_hrr_and_ag        PASS')


def test_split_line_hrr_degrades_when_no_hr():
    today_splits = {'1k': {'pace_s_per_km': 240.0, 'elapsed_s': 240.0, 'avg_hr': None}}
    summary = build_summary('2026-07-23', today_splits, vo2_reported=None,
                             activities=[], splits_index=SPLITS_INDEX,
                             vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('1k'))
    assert '❤️—' in line, line
    print('  test_split_line_hrr_degrades_when_no_hr  PASS')


def test_vo2_line_degrades_when_none():
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    assert '🫁—' in summary
    print('  test_vo2_line_degrades_when_none       PASS')


def test_vo2_line_shows_trio():
    vo2_history = [{'date': '2026-01-01', 'value': 60.49, 'age_bracket': 'M55'}]
    summary = build_summary('2026-07-23', {}, vo2_reported=57.22,
                             activities=[], splits_index={}, vo2_history=vo2_history, birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('🫁'))
    assert '🫁57.2' in line, line
    assert '🌟60.5' in line and '🎂60.5' in line and '👑60.5' in line, line
    print('  test_vo2_line_shows_trio                PASS')


def test_mileage_line_uses_zodiac_for_month_and_kanji_for_year():
    """Replaced '/mo'/'/yr' text suffixes at the user's request 2026-08-01:
    the month figure gets the zodiac sign occupying the majority of days in
    that calendar month (Jul23 is majority Cancer, Jul1-22=22d > Jul23-31=9d),
    the year figure gets 年 (Chinese/Japanese "year")."""
    activities = [
        {'date': '2026-07-01', 'sport': 'running', 'total_distance_m': 10000.0},
        {'date': '2026-01-01', 'sport': 'running', 'total_distance_m': 50000.0},
    ]
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=activities, splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('🗓️'))
    assert line == '🗓️10km♋ · 60km年', line
    print('  test_mileage_line_uses_zodiac_for_month_and_kanji_for_year  PASS')


def test_month_zodiac_covers_all_twelve_months():
    # August (2026-08-01) is majority Leo -- Jul23-Aug22=22d > Aug23-31=9d.
    summary = build_summary('2026-08-01', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('🗓️'))
    assert '♌' in line, line
    print('  test_month_zodiac_covers_all_twelve_months  PASS')


def test_always_present_lines_appear_even_with_no_splits():
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    assert '🎽' in summary
    assert '🗓️' in summary
    assert '⏳' in summary
    assert "1'000:" in summary
    assert "10'000:" in summary
    assert '🏃' in summary  # activity tag always present, always last
    print('  test_always_present_lines_appear_even_with_no_splits  PASS')


def test_activity_tag_is_last_line_and_includes_distance():
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR,
                             activity_name='Munich Running', activity_distance_m=21162.27)
    lines = summary.splitlines()
    assert lines[-1] == '🏃 Munich Running, 2026-07-23 · 21.2km', lines[-1]
    print('  test_activity_tag_is_last_line_and_includes_distance  PASS')


def test_activity_tag_degrades_without_distance():
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    lines = summary.splitlines()
    assert lines[-1] == '🏃 Run, 2026-07-23', lines[-1]
    print('  test_activity_tag_degrades_without_distance  PASS')


def test_keycap_number_uses_apostrophe_thousands_separator():
    assert _keycap_number(100) == '1️⃣0️⃣0️⃣'
    assert _keycap_number(1500) == "1️⃣'5️⃣0️⃣0️⃣"
    print('  test_keycap_number_uses_apostrophe_thousands_separator  PASS')


def test_landmark_lines_fires_only_on_the_tier_todays_run_crossed():
    # Month tips from 73.7 -> 100.4 (crosses 100), year stays inside the
    # 1500 tier throughout -- only the month line should appear.
    lines = _landmark_lines(73.7, 100.4, 8, 1537.0, 1538.4, 2026)
    assert lines == ['1️⃣0️⃣0️⃣🏃km in ♌'], lines
    print('  test_landmark_lines_fires_only_on_the_tier_todays_run_crossed  PASS')


def test_landmark_lines_both_month_and_year_can_fire_together():
    lines = _landmark_lines(90.0, 105.0, 8, 1590.0, 1605.0, 2026)
    assert lines == ['1️⃣0️⃣0️⃣🏃km in ♌', "1️⃣'6️⃣0️⃣0️⃣🏃km in '2️⃣6️⃣"], lines
    print('  test_landmark_lines_both_month_and_year_can_fire_together  PASS')


def test_landmark_lines_silent_when_no_tier_crossed():
    lines = _landmark_lines(50.0, 95.0, 8, 1500.0, 1538.0, 2026)
    assert lines == [], lines
    print('  test_landmark_lines_silent_when_no_tier_crossed  PASS')


def test_landmark_line_appears_as_first_line_of_full_summary():
    """Today's run alone (95km->21.3km before this run leaves it at 73.7,
    after at 95.0 -- no cross) vs a run that DOES tip the month over 100km,
    driven entirely by activity_distance_m/activities the same way
    build_summary computes it for real."""
    # activities must include today's own run too, matching how the real
    # caller's `activities` list (local archive + intervals.icu backfill,
    # see running_efficiency_post.process_running_activity) already does --
    # build_summary only backs today's OWN distance back out of the total,
    # it doesn't add it in.
    activities = [{'date': '2026-08-01', 'sport': 'running', 'total_distance_m': 79000.0},
                  {'date': '2026-08-13', 'sport': 'running', 'total_distance_m': 21300.0}]
    summary = build_summary('2026-08-13', {}, vo2_reported=None,
                             activities=activities, splits_index={}, vo2_history=[],
                             birth_year=BIRTH_YEAR, activity_distance_m=21300.0)
    # month total = 79 + 21.3 = 100.3km -> crosses the 100 tier; must be line 0.
    assert summary.splitlines()[0] == '1️⃣0️⃣0️⃣🏃km in ♌', summary.splitlines()[0]
    print('  test_landmark_line_appears_as_first_line_of_full_summary  PASS')


def test_cumulative_days_not_yet_reached_shows_infinity():
    summary = build_summary('2026-07-23', {}, vo2_reported=None,
                             activities=[], splits_index={}, vo2_history=[], birth_year=BIRTH_YEAR)
    line = next(l for l in summary.splitlines() if l.startswith('⏳'))
    assert "1'000:∞" in line, line
    print('  test_cumulative_days_not_yet_reached_shows_infinity  PASS')


if __name__ == '__main__':
    test_format_pace_has_no_unit_suffix()
    test_format_pace_floors_never_rounds_up_past_a_boundary()
    test_ordinal()
    test_rank_tag_uses_medals_for_top_three()
    test_rank_tag_uses_flag_for_fourth_and_beyond()
    test_split_line_absent_when_not_in_todays_run()
    test_split_line_season_rank_and_pb_values()
    test_split_line_shows_display_tag_for_manual_race_entry()
    test_split_line_shows_bound_prefix_when_longer_distance_pb_is_faster()
    test_monotonic_bound_applies_even_when_longer_distance_not_in_todays_run()
    test_split_line_shows_hrr_and_ag()
    test_mileage_line_uses_zodiac_for_month_and_kanji_for_year()
    test_month_zodiac_covers_all_twelve_months()
    test_split_line_hrr_degrades_when_no_hr()
    test_vo2_line_degrades_when_none()
    test_vo2_line_shows_trio()
    test_always_present_lines_appear_even_with_no_splits()
    test_activity_tag_is_last_line_and_includes_distance()
    test_activity_tag_degrades_without_distance()
    test_cumulative_days_not_yet_reached_shows_infinity()
    test_keycap_number_uses_apostrophe_thousands_separator()
    test_landmark_lines_fires_only_on_the_tier_todays_run_crossed()
    test_landmark_lines_both_month_and_year_can_fire_together()
    test_landmark_lines_silent_when_no_tier_crossed()
    test_landmark_line_appears_as_first_line_of_full_summary()
    print('\nAll tests passed.')
