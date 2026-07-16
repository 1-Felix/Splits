# gen_max_plan.py — generates Max's plan-data.js (beginner -> half marathon).
# 40 weeks, Mon 2026-07-20 .. race Sun 2027-04-25, 3 sessions/week (Tue/Thu/Sun).
import sys, json
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8")

START = date(2026, 7, 20)           # Wk 1 Monday
RACE = date(2027, 4, 25)            # race Sunday
assert START.weekday() == 0 and RACE.weekday() == 6
N_WEEKS = (RACE - START).days // 7 + 1
assert N_WEEKS == 40, N_WEEKS

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

def rest(day, d):
    return {"day": day, "date": d.isoformat(), "kind": "rest", "title": "Rest",
            "load": "Easy", "km": 0, "detail": "Rest day — an easy walk is always fine."}

def runwalk(title, km, reps, jog, walk, note=None):
    return {"kind": "run", "title": title, "load": "Easy", "km": km, "zone": "Z2",
            "detail": f"5 min walk wu · {reps}×({jog} jog / {walk} walk) · 5 min walk cd",
            "segments": [
                {"label": "Warm-up", "val": "5 min brisk walk"},
                {"label": "Reps", "val": f"{reps}×{jog} jog", "rest": f"{walk} walk"},
                {"label": "Cool-down", "val": "5 min walk"},
            ],
            "extra": note or "Jog = conversational, nose-breathing slow. Walk breaks are the plan, not a failure."}

def easy(title, km, mins=None, note=None, strides=False):
    d = {"kind": "run", "title": title, "load": "Easy", "km": km, "zone": "Z2",
         "pace": "~8:00–8:45",
         "detail": (f"{mins} min easy" if mins else f"{km} km easy") + " · conversational" + (" · 4×15 s strides after" if strides else ""),
         "segments": [{"label": "Easy", "val": (f"{mins} min" if mins else f"{km} km") + " @ conversational"}]}
    if strides:
        d["segments"].append({"label": "Strides", "val": "4×15 s quick, tall form", "rest": "60 s walk"})
    if note: d["extra"] = note
    return d

def steady(title, km, body, segments, load="Moderate", pace=None, zone=None, note=None):
    d = {"kind": "run", "title": title, "load": load, "km": km, "detail": body, "segments": segments}
    if pace: d["pace"] = pace
    if zone: d["zone"] = zone
    if note: d["extra"] = note
    return d

def longrun(km, note=None, fuel=None, finish=None):
    segs = [{"label": "Steady", "val": f"{km} km @ conversational"}]
    detail = f"{km} km long · easy, walk breaks allowed"
    if finish:
        segs = [{"label": "Steady", "val": f"{km - finish} km easy"},
                {"label": "Finish", "val": f"last {finish} km @ race pace (~7:07)"}]
        detail = f"{km} km long · last {finish} km at race pace"
    d = {"kind": "run", "title": "Long Run", "load": "Moderate", "km": km, "zone": "Z2",
         "detail": detail, "segments": segs}
    if fuel: d["fuel"] = fuel
    if note: d["extra"] = note
    return d

# ── the 40-week arc: (phase, focus, tue, thu, sun) ───────────────────────────
W = []

# Phase 1 — Run/Walk Foundation (Wk 1–8): to 30 min continuous
W.append(("Run/Walk", "Start the engine · 1:1 intervals",
          runwalk("Run/Walk 1:1", 2.5, 8, "1 min", "1 min"),
          runwalk("Run/Walk 1:1", 2.5, 8, "1 min", "1 min"),
          runwalk("Run/Walk 1:1 · Long", 3, 10, "1 min", "1 min")))
W.append(("Run/Walk", "Double the jog · 2:1",
          runwalk("Run/Walk 2:1", 3, 7, "2 min", "1 min"),
          runwalk("Run/Walk 2:1", 3, 7, "2 min", "1 min"),
          runwalk("Run/Walk 2:1 · Long", 3.5, 8, "2 min", "1 min")))
W.append(("Run/Walk", "3-minute blocks",
          runwalk("Run/Walk 3:1", 3.5, 6, "3 min", "1 min"),
          runwalk("Run/Walk 3:1", 3.5, 6, "3 min", "1 min"),
          runwalk("Run/Walk 3:1 · Long", 4, 7, "3 min", "1 min")))
W.append(("Run/Walk", "Absorb week · repeat 3:1 lighter",
          runwalk("Run/Walk 3:1", 3, 5, "3 min", "1 min"),
          runwalk("Run/Walk 3:1", 3, 5, "3 min", "1 min"),
          runwalk("Run/Walk 3:1 · Long", 3.5, 6, "3 min", "1 min",
                  "Cutback on purpose — let the legs absorb three build weeks.")))
W.append(("Run/Walk", "5-minute blocks",
          runwalk("Run/Walk 5:1½", 4, 5, "5 min", "90 s"),
          runwalk("Run/Walk 5:1½", 4, 5, "5 min", "90 s"),
          runwalk("Run/Walk 5:1½ · Long", 4.5, 6, "5 min", "90 s")))
W.append(("Run/Walk", "8-minute blocks — nearly there",
          runwalk("Run/Walk 8:2", 4.5, 4, "8 min", "2 min"),
          runwalk("Run/Walk 8:2", 4.5, 4, "8 min", "2 min"),
          runwalk("Run/Walk 10:2 · Long", 5, 3, "10 min", "2 min")))
W.append(("Run/Walk", "Quarter-hour blocks",
          runwalk("Run/Walk 15:2", 4.5, 2, "15 min", "2 min"),
          runwalk("Run/Walk 15:2", 4.5, 2, "15 min", "2 min"),
          steady("Long Run/Walk", 5, "20 min jog · 5 min walk · 10 min jog", [
              {"label": "Jog", "val": "20 min"},
              {"label": "Walk", "val": "5 min"},
              {"label": "Jog", "val": "10 min"}], load="Easy", zone="Z2")))
W.append(("Run/Walk", "MILESTONE · 30 min continuous",
          easy("Easy Run", 4.5, mins=25),
          easy("Easy Run", 4, mins=20, note="Deliberately short — save the legs for Sunday's milestone."),
          steady("30 min Continuous", 5, "30 min continuous jog — the first goal falls", [
              {"label": "Run", "val": "30 min continuous @ conversational"}], load="Easy", zone="Z2",
              note="Milestone run. Any pace counts — finishing without walking is the whole workout.")))

# Phase 2 — Base to 5K (Wk 9–16)
p2 = [
    ("Consolidate 30 min", 4.5, 25, 4.5, 25, 5.5, 35, False, None),
    ("Extend the long run", 4.5, 25, 5, 30, 6, 40, False, None),
    ("Add gentle strides", 5, 28, 5, 30, 6.5, 42, True, None),
    ("Hold · absorb", 4.5, 25, 4.5, 25, 5.5, 35, True, "Cutback — absorb, don't build."),
    ("Long run to 50 min", 5, 28, 5.5, 32, 7.5, 50, True, None),
    ("Steady week", 5, 28, 5.5, 32, 8, 52, True, None),
    ("Pre-test week", 5, 28, 5, 30, 8.5, 55, True, None),
    ("5K TEST — first benchmark", 5, 28, 4, 22, 5, None, True, None),
]
for i, (focus, tkm, tmin, hkm, hmin, skm, smin, strides, cut) in enumerate(p2):
    if i == 7:
        sun = steady("5K Time Trial", 5, "2 km easy wu · 5 km steady-hard (a relaxed parkrun effort) · walk cd", [
            {"label": "Warm-up", "val": "2 km easy"},
            {"label": "Test", "val": "5 km steady-hard — even effort"},
            {"label": "Cool-down", "val": "5 min walk"}], load="Hard", zone="Z4",
            note="First benchmark: calibrates HR zones and the race predictor. Even pacing beats a fast start.")
        sun["km"] = 7
    else:
        sun = easy("Long Run", skm, mins=smin, note=cut)
        sun["title"], sun["load"] = "Long Run", "Moderate"
    W.append(("Base 5K", focus,
              easy("Easy Run", tkm, mins=tmin),
              easy("Easy Run", hkm, mins=hmin, strides=strides),
              sun))

# Phase 3 — Base to 10K (Wk 17–26)
p3 = [
    ("Into real kilometres", 5.5, 6, 8, False, None),
    ("Long run to 9", 5.5, 6, 9, False, None),
    ("Gentle hills join", 5.5, 6.5, 9.5, True, None),
    ("Cutback · absorb", 5, 5.5, 7, False, "Cutback — absorb, don't build."),
    ("Long run to 10", 6, 6.5, 10, True, None),
    ("Hold 10", 6, 6.5, 10.5, True, None),
    ("Holiday week · keep it light", 5, 5.5, 8, False, "Christmas week — three relaxed runs, zero pressure, enjoy the food."),
    ("Back to building", 6, 7, 11, True, None),
    ("Long run to 12", 6, 7, 12, True, None),
    ("10K TEST — second benchmark", 6, 5, None, True, None),
]
for i, (focus, tkm, hkm, skm, hills, note) in enumerate(p3):
    thu = easy("Easy Run", hkm, strides=not hills)
    if hills:
        thu = steady("Hills · Easy", hkm, f"{hkm} km easy with 6×45 s gentle hill strides inside", [
            {"label": "Easy", "val": f"{hkm - 1} km @ conversational"},
            {"label": "Hills", "val": "6×45 s uphill, easy effort", "rest": "walk down"}],
            load="Moderate", zone="Z3")
    if i == 9:
        sun = steady("10K Time Trial", 10, "1.5 km easy wu · 10 km steady (comfortably strong) · walk cd", [
            {"label": "Warm-up", "val": "1.5 km easy"},
            {"label": "Test", "val": "10 km steady — comfortably strong, even effort"},
            {"label": "Cool-down", "val": "5 min walk"}], load="Hard", zone="Z3",
            note="Second benchmark — double-digit territory. This pins the half-marathon pace for the build.")
        sun["km"] = 11.5
    else:
        sun = longrun(skm, note=note)
    W.append(("Base 10K", focus, easy("Easy Run", tkm), thu, sun))

# Phase 4 — Build (Wk 27–34)
p4 = [
    ("Tempo joins the week", 6.5, ("Tempo Blocks", 3, 5), 6, 12, None),
    ("Extend the tempo", 7, ("Tempo Blocks", 3, 6), 6, 13, None),
    ("Long run to 14", 7, ("Tempo Blocks", 2, 10), 6, 14, None),
    ("Cutback · absorb", 5.5, None, 5.5, 10, "Cutback — absorb, don't build."),
    ("Continuous tempo", 7.5, ("Steady Tempo", 1, 15), 6, 14, None),
    ("Long run to 15", 7.5, ("Steady Tempo", 1, 18), 6, 15, None),
    ("Biggest tempo yet", 8, ("Steady Tempo", 1, 20), 6, 16, None),
    ("Cutback before the peak", 6, None, 5.5, 11, "Last cutback before the half-specific block."),
]
for focus, tkm, tempo, hkm, skm, note in p4:
    if tempo:
        name, reps, mins = tempo
        if reps == 1:
            segs = [{"label": "Warm-up", "val": "2 km easy"},
                    {"label": "Tempo", "val": f"{mins} min @ ~6:50–7:05 (comfortably hard)"},
                    {"label": "Cool-down", "val": "1.5 km easy"}]
            body = f"2 wu · {mins} min tempo · 1.5 cd"
        else:
            segs = [{"label": "Warm-up", "val": "2 km easy"},
                    {"label": "Reps", "val": f"{reps}×{mins} min @ ~6:50–7:05", "rest": "2 min jog"},
                    {"label": "Cool-down", "val": "1.5 km easy"}]
            body = f"2 wu · {reps}×{mins} min tempo (2 min jog) · 1.5 cd"
        tue = steady(name, tkm, body, segs, load="Hard", pace="6:50–7:05", zone="Z3",
                     note="Comfortably hard — could speak in short sentences. If it feels like racing, ease off.")
    else:
        tue = easy("Easy Run", tkm)
    W.append(("Build", focus, tue, easy("Easy Run", hkm, strides=True),
              longrun(skm, fuel="drink from 10 km" if skm >= 12 else None)))

# Phase 5 — Half-Specific (Wk 35–38)
p5 = [
    ("Race pace enters", ("Race-Pace Reps", 3, 2.0), 6, 16, 3, None),
    ("Long run to 17", ("Race-Pace Reps", 3, 2.5), 6, 17, 4, None),
    ("PEAK · longest run", ("Race-Pace Reps", 2, 4.0), 6, 18, 5, "Peak week — after this it only gets easier."),
    ("Begin the descent", ("Race-Pace Reps", 2, 3.0), 5.5, 13, 4, None),
]
for focus, (name, reps, repkm), hkm, skm, finish, note in p5:
    tkm = round(2 + reps * repkm + 1.5, 1)
    tue = steady(name, tkm,
                 f"2 wu · {reps}×{repkm} km @ race pace ~7:07 (2–3 min jog) · 1.5 cd",
                 [{"label": "Warm-up", "val": "2 km easy"},
                  {"label": "Reps", "val": f"{reps}×{repkm} km @ ~7:07", "rest": "2–3 min jog"},
                  {"label": "Cool-down", "val": "1.5 km easy"}],
                 load="Hard", pace="~7:07", zone="Z3",
                 note="Race pace should feel almost easy at first — that's the point of it.")
    W.append(("Half-Specific", focus, tue, easy("Easy Run", hkm, strides=True),
              longrun(skm, note=note, fuel="gel @ 8 km · drink throughout" if skm >= 15 else "drink from 10 km",
                      finish=finish)))

# Phase 6 — Taper (Wk 39–40)
W.append(("Taper", "Volume down · legs fresh",
          easy("Easy Run", 4.5, strides=True),
          steady("Race-Pace Touch", 5, "2 easy · 2 km @ race pace · 1 easy", [
              {"label": "Easy", "val": "2 km"},
              {"label": "Race pace", "val": "2 km @ ~7:07"},
              {"label": "Easy", "val": "1 km"}], load="Moderate", pace="~7:07", zone="Z3"),
          longrun(8, note="Half the usual long — the fitness is banked; the taper is for the legs.")))
W.append(("Race Week", "RACE WEEK — first half marathon",
          easy("Easy Run", 4, note="4×15 s strides — stay springy, nothing hard.", strides=True),
          steady("Shakeout", 3, "3 km very easy · 2×15 s strides", [
              {"label": "Easy", "val": "3 km very easy"},
              {"label": "Strides", "val": "2×15 s"}], load="Easy", zone="Z1"),
          steady("RACE · Half Marathon", 21.1,
                 "Settle the first 5 · cruise to 16 · bring it home. Sub-2:30 is the stretch; FINISHING is the win.",
                 [{"label": "Settle", "val": "km 0–5 — slower than feels right"},
                  {"label": "Cruise", "val": "km 5–16 @ ~7:07"},
                  {"label": "Race", "val": "km 16–21 — whatever is left"}],
                 load="Hard", pace="~7:07", zone="Z3",
                 note="First half marathon. Start slow, fuel early (gel @ 7 & 14 km), smile at the finish.")))

assert len(W) == N_WEEKS, len(W)

# ── assemble block ────────────────────────────────────────────────────────────
block = []
for i, (phase, focus, tue, thu, sun) in enumerate(W):
    mon = START + timedelta(weeks=i)
    dates = [mon + timedelta(days=d) for d in range(7)]
    # Max's running days: Mon / Wed / Sat (long run Saturday). Race week is the
    # one exception — the race itself is Sunday, so Saturday becomes a short
    # pre-race leg-loosener and the "long" slot moves to race day.
    is_race_week = (i == N_WEEKS - 1)
    if is_race_week:
        prerace = steady("Pre-Race Strides", 2, "10 min very easy + 3×15 s strides — wake the legs, nothing more", [
            {"label": "Easy", "val": "10 min very easy"},
            {"label": "Strides", "val": "3×15 s"}], load="Easy", zone="Z1")
        sessions = {"Mon": tue, "Wed": thu, "Sat": prerace, "Sun": sun}
    else:
        sessions = {"Mon": tue, "Wed": thu, "Sat": sun}
    days = []
    for dow, d in zip(DOW, dates):
        if dow in sessions:
            s = dict(sessions[dow]); s["day"] = dow; s["date"] = d.isoformat()
            days.append(s)
        else:
            days.append(rest(dow, d))
    is_race = is_race_week
    km = round(sum(d["km"] for d in days) - (21.1 if is_race else 0), 1)
    km = int(km) if km == int(km) else km
    long_km = 21.1 if is_race else max(d["km"] for d in days)
    block.append({
        "wk": f"Wk {i + 1}", "label": f"{mon.strftime('%b')} {mon.day}",
        "mon": mon.isoformat(), "sun": dates[6].isoformat(),
        "phase": phase, "km": km,
        "long": "21.1 km RACE" if is_race else (f"{long_km} km" if long_km == int(long_km) else f"{long_km} km"),
        "focus": focus, "days": days,
    })
    block[-1]["label"] = f"{mon.strftime('%b')} {mon.day}"

plan = {
    "race": {
        "name": "First Half Marathon",
        "location": "Allgäu · race TBD",
        "date": RACE.isoformat(),
        "distanceKm": 21.1,
        "goalTime": "2:29:59",
        "goalPaceSecPerKm": 427,
        "pb": None,
        "pbDate": None,
    },
    "block": block,
    "coach": {
        "headline": "Not one 40-week plan — three short campaigns: a 5K by autumn, a 10K by winter, the half in spring.",
        "note": "Max starts from weekly run/walks (~3.5 km with Felix). The arc: 8 weeks run/walk to 30 min continuous, 8 weeks to a 5K benchmark, 10 weeks of aerobic base to a 10K test, 8 weeks of build with tempo, 4 half-specific weeks peaking at an 18 km long run, 2-week taper into a spring half in the Allgäu (race TBD — the block re-anchors when he registers). Three days a week — Mon/Wed/Sat, long run Saturday (race day itself is the one Sunday). Motivation is engineered, not hoped for: enter the Wk 16 5K and the Wk 26 10K as REAL events (parkrun counts) so there's always a finish line within ~10 weeks. The 10K test (late January) is the formal re-calculation checkpoint: with six months of real data, ahead-of-curve → consider re-anchoring to a March half; behind → April stays. Sub-2:30 is the stretch goal; finishing healthy is the actual goal. Rules: walk breaks are a tool, not a failure; any pain that changes the stride ends the run; a missed week just slides — the plan has slack built in.",
        "focus": [
            "Three sessions a week, every week — consistency IS the plan",
            "Campaign 1: 30 min continuous (Wk 8), then a real 5K (Wk 16)",
            "Everything conversational — if he can't talk, it's too fast; walk breaks are a tool",
            "10K test (Wk 26, late Jan) = re-calculation checkpoint: re-anchor shorter if he's ahead of curve",
        ],
        "log": [
            {"date": "2026-07-16",
             "text": "Plan authored (Felix + AI): beginner→half anchored on a spring-2027 Allgäu half (exact race TBD — re-anchor when he registers). Start point: weekly run/walks ~3.5 km. Days set to Mon/Wed/Sat per Felix (long run Saturday; race day is the one Sunday). The 40-week length was debated — physiologically ~26-28 weeks would do, but the race calendar's earliest real window is March (~34 wks), so the April anchor holds and the length is managed as three campaigns instead: 5K event at Wk 16, 10K event at Wk 26, half in spring. The Wk 26 10K is the explicit re-calculation gate — re-anchor to a March half if the data says he's ahead. Structure: run/walk foundation → 30 min continuous (Wk 8) → 5K → aerobic base → 10K → tempo build → 18 km peak (Wk 37) → 2-week taper; peak ~35 km/wk. Zones calibrate from watch data once the Health Connect bridge feeds real runs; until then everything is effort-based on purpose."},
        ],
    },
}

HEADER = """/* =============================================================================
 *  plan-data.js — MAX'S LIVE PLAN (coach-owned: Felix + AI).
 *
 *  Beginner → first half marathon. 40 weeks, Mon 2026-07-20 → race Sun
 *  2027-04-25 (spring Allgäu half, exact race TBD — re-anchor when he
 *  registers). 3 sessions/week (Tue/Thu/Sun), rest days rendered as easy
 *  cross cards. Fully detailed to race day per the standing rule; the weekly
 *  ritual adjusts weeks from actuals — it never authors them late.
 *
 *  Generated 2026-07-16 (gen_max_plan.py); hand-edit freely — the generator
 *  is a one-shot authoring tool, not an owner.
 * ========================================================================== */

export const planData = """

out = HEADER + json.dumps(plan, indent=2, ensure_ascii=False) + ";\n\nexport default planData;\n"
path = sys.argv[1]
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(out)

kms = [w["km"] for w in block]
print(f"weeks={len(block)} race={RACE} peak_km={max(kms)} first_weeks_km={kms[:8]}")
print(f"phase weeks: ", {p: sum(1 for w in block if w['phase'] == p) for p in dict.fromkeys(w['phase'] for w in block)})
