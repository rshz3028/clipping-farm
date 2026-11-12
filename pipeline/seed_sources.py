"""Seed the registry with sources whose licences were checked by hand on 2026-11-11.

Usage:
    python -m pipeline seed
"""
from pipeline.core import registry
from pipeline.discover.finders.nasa_images import make_record as nasa_record
from pipeline.discover.finders.prelinger import make_record as prelinger_record

CHECKED = "2026-11-11"

SOURCES = [
    nasa_record("nasa_apollo11_launch",
                "KSC-19690716-MH-NAS01-0001-Apollo_11_Launch_President_Johnson_Jack_King_Narration_Press_Site-B_1372",
                "Apollo 11 Pre-Launch and Launch (1969)"),
    nasa_record("nasa_saturnv_crawler", "KSC-1960s-MH-NAS01-0001-Apollo_Saturn_V_Crawler,_VAB_Pad_Film_To_Tape",
                "Film to Tape - Apollo, Saturn V, Crawler, VAB, Pad 39A"),
    nasa_record("nasa_skylab_flammability", "GRC-2022-CM-0138",
                "Skylab Zero-G Flammability Studies - 16mm Film Transfer"),
    nasa_record("nasa_x15_documentary", "NDTV001077-X-15_Documentary_Revised", "X-15 Documentary"),
    nasa_record("nasa_1971_highlights", "1971 Aeronautics and Space Highlights", "1971 Aeronautics and Space Highlights"),
    prelinger_record("pre_a_is_for_atom", "isforAto1953", "A is for Atom (1953)",
                     "Sutherland (John) Productions / sponsor General Electric; Prelinger Archives"),
    prelinger_record("pre_bacteria", "bacteria_friend_and_foe", "Bacteria: Friend and Foe",
                     "Encyclopedia Britannica Films; Prelinger Archives"),
    prelinger_record("pre_sleep_for_health", "Sleepfor1950", "Sleep for Health (1950)",
                     "Encyclopaedia Britannica Films; Prelinger Archives"),
    prelinger_record("pre_preventing_disease", "Preventi1940", "Preventing the Spread of Disease (1940)",
                     "National Motion Picture Company; Prelinger Archives"),
    prelinger_record("pre_exercise_health", "Exercise1949", "Exercise and Health (1949)",
                     "Coronet Instructional Films; Prelinger Archives"),
]
for _s in SOURCES:
    _s["date_checked"] = CHECKED


def seed() -> None:
    for s in SOURCES:
        registry.upsert(s)
    print(f"Seeded {len(SOURCES)} sources.")
