import math
from datetime import date, datetime, time, timedelta
from io import BytesIO

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Smart Study Planner",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    [data-testid="stSidebar"] {
        min-width: 310px;
    }

    .planner-muted {
        opacity: .72;
        font-size: .88rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📚 Smart Study Planner")

st.caption(
    "Build a realistic weekly plan around courses, study time, projects, "
    "fixed events, travel, tasks, and reminders."
)


# =========================================================
# SESSION STATE
# =========================================================

DEFAULTS = {
    "courses": [],
    "work_windows": [],
    "events": [],
    "study_topics": [],
    "academic_work": [],
    "tasks": [],
    "reminders": [],
    "schedule": [],
    "week_offset": 0,

    # Planner preferences
    "include_breaks": True,
    "break_after_minutes": 60,
    "break_length_minutes": 15,
    "preferred_study_minutes": 60,
    "max_study_minutes": 90,
    "daily_academic_cap": 360,
    "use_course_cap": True,
    "daily_course_cap": 180,

    # UI
    "show_preferences": True,
    "work_days_picker": [],
}


for key, default_value in DEFAULTS.items():

    if key not in st.session_state:

        if isinstance(default_value, list):
            st.session_state[key] = []

        else:
            st.session_state[key] = default_value


# =========================================================
# CONSTANTS
# =========================================================

DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

WEEKDAYS = DAYS[:5]

PRIORITY_VALUE = {
    "Low": 1,
    "Normal": 2,
    "High": 3,
}


# =========================================================
# GENERAL HELPERS
# =========================================================

def next_id(collection):

    if not collection:
        return 1

    return max(
        item["id"]
        for item in collection
    ) + 1


def get_week_start(day):

    return day - timedelta(
        days=day.weekday()
    )


def get_visible_week():

    monday = (
        get_week_start(date.today())
        + timedelta(
            weeks=st.session_state.week_offset
        )
    )

    return [
        monday + timedelta(days=i)
        for i in range(7)
    ]


def format_minutes(minutes):

    minutes = max(
        0,
        int(round(minutes)),
    )

    hours, mins = divmod(
        minutes,
        60,
    )

    if hours and mins:
        return f"{hours}h {mins}m"

    if hours:
        return f"{hours}h"

    return f"{mins}m"


def combine(day, clock_time):

    return datetime.combine(
        day,
        clock_time,
    )


def minutes_between(start, end):

    return max(
        0,
        int(
            (end - start).total_seconds()
            / 60
        ),
    )


def priority_number(priority):

    return PRIORITY_VALUE.get(
        priority,
        2,
    )


def deadline_urgency(deadline):

    days_left = (
        deadline - date.today()
    ).days

    if days_left < 0:
        return 100

    if days_left == 0:
        return 95

    if days_left == 1:
        return 85

    if days_left <= 3:
        return 70

    if days_left <= 7:
        return 50

    if days_left <= 14:
        return 30

    return 15


def item_score(item):

    return (
        deadline_urgency(
            item["deadline"]
        )
        + (
            priority_number(
                item.get(
                    "priority",
                    "Normal",
                )
            )
            * 10
        )
    )


def course_by_name(name):

    for course in st.session_state.courses:

        if course["name"] == name:
            return course

    return None


def course_color(name):

    course = course_by_name(
        name
    )

    if course:
        return course["color"]

    return "#777777"


# =========================================================
# STUDY TIME CALCULATOR
# =========================================================

def calculate_study_time(
    difficulty,
    familiarity,
    goal,
):

    base_times = {
        "Easy": 60,
        "Medium": 120,
        "Hard": 180,
    }

    familiarity_multiplier = {
        "Never seen it": 1.5,
        "Some exposure": 1.2,
        "Comfortable": 0.8,
        "Review only": 0.5,
    }

    goal_multiplier = {
        "Understand the basics": 1.0,
        "Complete practice problems": 1.25,
        "Use it in a project": 1.5,
        "Prepare for a test": 1.3,
    }

    return round(
        base_times[difficulty]
        * familiarity_multiplier[familiarity]
        * goal_multiplier[goal]
    )


# =========================================================
# WORK WINDOWS
# =========================================================

def merge_intervals(intervals):

    if not intervals:
        return []

    intervals = sorted(
        intervals,
        key=lambda item: item[0],
    )

    merged = [
        intervals[0]
    ]

    for (
        current_start,
        current_end,
    ) in intervals[1:]:

        (
            previous_start,
            previous_end,
        ) = merged[-1]

        if current_start <= previous_end:

            merged[-1] = (
                previous_start,
                max(
                    previous_end,
                    current_end,
                ),
            )

        else:

            merged.append(
                (
                    current_start,
                    current_end,
                )
            )

    return merged


def work_windows_for_date(day):

    weekday = day.strftime(
        "%A"
    )

    intervals = []

    for window in st.session_state.work_windows:

        if weekday not in window["days"]:
            continue

        start = combine(
            day,
            window["start_time"],
        )

        end = combine(
            day,
            window["end_time"],
        )

        if end > start:

            intervals.append(
                (
                    start,
                    end,
                )
            )

    return merge_intervals(
        intervals
    )


# =========================================================
# EVENTS
# =========================================================

def events_for_date(day):

    weekday = day.strftime(
        "%A"
    )

    results = []

    for event in st.session_state.events:

        if event["recurring"]:

            include = (
                weekday
                in event["days"]
            )

        else:

            include = (
                event["date"]
                == day
            )

        if not include:
            continue

        actual_start = combine(
            day,
            event["start_time"],
        )

        actual_end = combine(
            day,
            event["end_time"],
        )

        blocked_start = (
            actual_start
            - timedelta(
                minutes=event.get(
                    "buffer_before",
                    0,
                )
            )
        )

        blocked_end = (
            actual_end
            + timedelta(
                minutes=event.get(
                    "buffer_after",
                    0,
                )
            )
        )

        results.append(
            {
                "id": event["id"],
                "name": event["name"],
                "actual_start": actual_start,
                "actual_end": actual_end,
                "blocked_start": blocked_start,
                "blocked_end": blocked_end,
                "location": event.get(
                    "location",
                    "",
                ),
                "notes": event.get(
                    "notes",
                    "",
                ),
                "url": event.get(
                    "url",
                    "",
                ),
                "type": "Event",
            }
        )

    return sorted(
        results,
        key=lambda item: item[
            "actual_start"
        ],
    )


# =========================================================
# REMINDER RESERVATIONS
# =========================================================

def reserved_reminders_for_date(day):

    results = []

    for reminder in st.session_state.reminders:

        if (
            reminder["date"] != day
            or reminder["reserve_minutes"] <= 0
        ):
            continue

        start = combine(
            day,
            reminder["time"],
        )

        end = (
            start
            + timedelta(
                minutes=reminder[
                    "reserve_minutes"
                ]
            )
        )

        results.append(
            (
                start,
                end,
            )
        )

    return results


# =========================================================
# FREE INTERVAL LOGIC
# =========================================================

def intervals_overlap(
    start1,
    end1,
    start2,
    end2,
):

    return (
        start1 < end2
        and start2 < end1
    )


def subtract_interval(
    intervals,
    blocked_start,
    blocked_end,
):

    result = []

    for start, end in intervals:

        if not intervals_overlap(
            start,
            end,
            blocked_start,
            blocked_end,
        ):

            result.append(
                (
                    start,
                    end,
                )
            )

            continue

        if start < blocked_start:

            result.append(
                (
                    start,
                    blocked_start,
                )
            )

        if blocked_end < end:

            result.append(
                (
                    blocked_end,
                    end,
                )
            )

    return result


def free_intervals_for_date(day):

    free = work_windows_for_date(
        day
    )

    # Block fixed events + travel buffers
    for event in events_for_date(
        day
    ):

        free = subtract_interval(
            free,
            event["blocked_start"],
            event["blocked_end"],
        )

    # Block reminders that reserve time
    for (
        start,
        end,
    ) in reserved_reminders_for_date(
        day
    ):

        free = subtract_interval(
            free,
            start,
            end,
        )

    # Block generated schedule
    for block in st.session_state.schedule:

        if block["date"] != day:
            continue

        free = subtract_interval(
            free,
            block["start"],
            block["end"],
        )

    return sorted(
        free,
        key=lambda item: item[0],
    )


# =========================================================
# DAILY LIMITS
# =========================================================

def academic_minutes_on_day(day):

    return sum(
        block["work_minutes"]
        for block
        in st.session_state.schedule
        if (
            block["date"] == day
            and block["type"]
            in {
                "Study",
                "Assignment",
                "Project",
            }
        )
    )


def course_minutes_on_day(
    day,
    course,
):

    return sum(
        block["work_minutes"]
        for block
        in st.session_state.schedule
        if (
            block["date"] == day
            and block.get(
                "course"
            ) == course
            and block["type"]
            in {
                "Study",
                "Assignment",
                "Project",
            }
        )
    )


def academic_capacity_left(day):

    return max(
        0,
        (
            st.session_state.daily_academic_cap
            - academic_minutes_on_day(
                day
            )
        ),
    )


def course_capacity_left(
    day,
    course,
):

    if not st.session_state.use_course_cap:
        return 100000

    return max(
        0,
        (
            st.session_state.daily_course_cap
            - course_minutes_on_day(
                day,
                course,
            )
        ),
    )


# =========================================================
# BREAKS
# =========================================================

def elapsed_time_needed(
    work_minutes,
):

    work_minutes = int(
        work_minutes
    )

    if not st.session_state.include_breaks:
        return work_minutes

    focus = (
        st.session_state.break_after_minutes
    )

    break_length = (
        st.session_state.break_length_minutes
    )

    if work_minutes <= focus:
        return work_minutes

    full_chunks = (
        work_minutes
        // focus
    )

    if (
        work_minutes
        % focus
        == 0
    ):

        breaks = max(
            0,
            full_chunks - 1,
        )

    else:

        breaks = full_chunks

    return (
        work_minutes
        + breaks * break_length
    )


def create_work_and_break_blocks(
    item,
    day,
    start,
    work_minutes,
):

    current = start
    remaining = work_minutes

    if st.session_state.include_breaks:

        focus_length = (
            st.session_state.break_after_minutes
        )

    else:

        focus_length = work_minutes

    while remaining > 0:

        focus_minutes = min(
            remaining,
            focus_length,
        )

        focus_end = (
            current
            + timedelta(
                minutes=focus_minutes
            )
        )

        st.session_state.schedule.append(
            {
                "name": item["name"],
                "course": item.get(
                    "course",
                    "",
                ),
                "type": item["type"],
                "date": day,
                "start": current,
                "end": focus_end,
                "work_minutes": focus_minutes,
                "deadline": item["deadline"],
                "source_id": item.get(
                    "source_id"
                ),
                "notes": item.get(
                    "notes",
                    "",
                ),
                "url": item.get(
                    "url",
                    "",
                ),
            }
        )

        remaining -= focus_minutes

        current = focus_end

        if (
            remaining > 0
            and st.session_state.include_breaks
        ):

            break_end = (
                current
                + timedelta(
                    minutes=(
                        st.session_state
                        .break_length_minutes
                    )
                )
            )

            st.session_state.schedule.append(
                {
                    "name": "Break",
                    "course": "",
                    "type": "Break",
                    "date": day,
                    "start": current,
                    "end": break_end,
                    "work_minutes": 0,
                    "deadline": item[
                        "deadline"
                    ],
                    "source_id": None,
                    "notes": "",
                    "url": "",
                }
            )

            current = break_end


# =========================================================
# FIND A SLOT
# =========================================================

def find_slot(
    day,
    requested_work_minutes,
    course="",
):

    daily_left = (
        academic_capacity_left(
            day
        )
    )

    if course:

        course_left = (
            course_capacity_left(
                day,
                course,
            )
        )

    else:

        course_left = 100000

    allowed_work = min(
        requested_work_minutes,
        daily_left,
        course_left,
    )

    if allowed_work <= 0:
        return None

    for (
        start,
        end,
    ) in free_intervals_for_date(
        day
    ):

        interval_minutes = (
            minutes_between(
                start,
                end,
            )
        )

        possible_work = (
            allowed_work
        )

        while possible_work >= 10:

            if (
                elapsed_time_needed(
                    possible_work
                )
                <= interval_minutes
            ):

                return (
                    start,
                    possible_work,
                )

            possible_work -= 5

    return None


# =========================================================
# COURSE-BATCHED STUDY SCHEDULER
# =========================================================

def course_study_score(
    course,
    day,
    remaining,
):

    topics = [
        topic
        for topic
        in st.session_state.study_topics
        if (
            topic["course"]
            == course
            and remaining.get(
                topic["id"],
                0,
            ) > 0
            and day
            <= topic["deadline"]
        )
    ]

    if not topics:
        return -1

    return max(
        item_score(
            topic
        )
        for topic in topics
    )


def schedule_study_topics():

    remaining = {
        topic["id"]:
        topic["recommended_minutes"]
        for topic
        in st.session_state.study_topics
    }

    if not remaining:
        return

    current_day = (
        date.today()
    )

    latest_deadline = max(
        topic["deadline"]
        for topic
        in st.session_state.study_topics
    )

    while (
        current_day
        <= latest_deadline
    ):

        active_courses = []

        all_courses = {
            topic["course"]
            for topic
            in st.session_state.study_topics
        }

        for course in all_courses:

            if (
                course_study_score(
                    course,
                    current_day,
                    remaining,
                )
                >= 0
            ):

                active_courses.append(
                    course
                )

        # Most urgent course first.
        # Once selected, stay on it until its daily cap
        # is used or its work is finished.
        active_courses.sort(
            key=lambda course: (
                -course_study_score(
                    course,
                    current_day,
                    remaining,
                ),
                course_minutes_on_day(
                    current_day,
                    course,
                ),
            )
        )

        for course in active_courses:

            while (
                academic_capacity_left(
                    current_day
                ) > 0
                and course_capacity_left(
                    current_day,
                    course,
                ) > 0
            ):

                topics = [
                    topic
                    for topic
                    in st.session_state.study_topics
                    if (
                        topic["course"]
                        == course
                        and remaining.get(
                            topic["id"],
                            0,
                        ) > 0
                        and current_day
                        <= topic[
                            "deadline"
                        ]
                    )
                ]

                if not topics:
                    break

                topics.sort(
                    key=lambda topic: (
                        -item_score(topic),
                        topic["deadline"],
                        remaining[
                            topic["id"]
                        ],
                    )
                )

                topic = topics[0]

                topic_id = (
                    topic["id"]
                )

                # Prefer full study blocks.
                # Short blocks are allowed only when
                # that is the final remainder.
                if (
                    remaining[topic_id]
                    <= st.session_state
                    .preferred_study_minutes
                ):

                    desired = (
                        remaining[
                            topic_id
                        ]
                    )

                else:

                    desired = (
                        st.session_state
                        .preferred_study_minutes
                    )

                desired = min(
                    desired,
                    topic[
                        "max_session_minutes"
                    ],
                    st.session_state
                    .max_study_minutes,
                    remaining[
                        topic_id
                    ],
                    course_capacity_left(
                        current_day,
                        course,
                    ),
                    academic_capacity_left(
                        current_day
                    ),
                )

                # Do not deliberately create
                # 30m Python → 30m Cloud nonsense.
                if (
                    desired < 60
                    and remaining[
                        topic_id
                    ] > desired
                ):

                    break

                slot = find_slot(
                    current_day,
                    desired,
                    course,
                )

                if slot is None:
                    break

                (
                    start,
                    actual_minutes,
                ) = slot

                item = {
                    "name": topic[
                        "topic"
                    ],
                    "course": topic[
                        "course"
                    ],
                    "type": "Study",
                    "deadline": topic[
                        "deadline"
                    ],
                    "source_id": (
                        topic_id
                    ),
                    "notes": topic.get(
                        "notes",
                        "",
                    ),
                    "url": topic.get(
                        "url",
                        "",
                    ),
                }

                create_work_and_break_blocks(
                    item,
                    current_day,
                    start,
                    actual_minutes,
                )

                remaining[
                    topic_id
                ] -= actual_minutes

        current_day += timedelta(
            days=1
        )


# =========================================================
# PROJECT DEPENDENCY CHECK
# =========================================================

def project_ready_date(
    work_item,
):

    linked_ids = (
        work_item.get(
            "linked_topic_ids",
            [],
        )
    )

    if not linked_ids:
        return date.today()

    final_dates = []

    for topic_id in linked_ids:

        topic = next(
            (
                topic
                for topic
                in st.session_state.study_topics
                if topic["id"]
                == topic_id
            ),
            None,
        )

        if topic is None:
            continue

        scheduled = [
            block
            for block
            in st.session_state.schedule
            if (
                block["type"]
                == "Study"
                and block.get(
                    "source_id"
                )
                == topic_id
            )
        ]

        scheduled_minutes = sum(
            block["work_minutes"]
            for block in scheduled
        )

        if (
            scheduled_minutes
            < topic[
                "recommended_minutes"
            ]
        ):

            return topic[
                "deadline"
            ]

        final_dates.append(
            max(
                block["date"]
                for block in scheduled
            )
        )

    if final_dates:
        return max(
            final_dates
        )

    return date.today()


# =========================================================
# COURSE-BATCHED ASSIGNMENTS / PROJECTS
# =========================================================

def schedule_academic_work():

    items = []

    for source in st.session_state.academic_work:

        item = source.copy()

        item[
            "remaining_minutes"
        ] = source[
            "estimated_minutes"
        ]

        items.append(
            item
        )

    if not items:
        return

    current_day = date.today()

    latest_deadline = max(
        item["deadline"]
        for item in items
    )

    while (
        current_day
        <= latest_deadline
    ):

        active_courses = []

        all_courses = {
            item["course"]
            for item in items
        }

        for course in all_courses:

            relevant = [
                item
                for item in items
                if (
                    item["course"]
                    == course
                    and item[
                        "remaining_minutes"
                    ] > 0
                    and current_day
                    <= item[
                        "deadline"
                    ]
                    and (
                        item["type"]
                        != "Project"
                        or current_day
                        >= project_ready_date(
                            item
                        )
                    )
                )
            ]

            if relevant:
                active_courses.append(
                    course
                )

        active_courses.sort(
            key=lambda course: (
                -max(
                    item_score(
                        item
                    )
                    for item in items
                    if (
                        item["course"]
                        == course
                        and item[
                            "remaining_minutes"
                        ] > 0
                    )
                ),
                course_minutes_on_day(
                    current_day,
                    course,
                ),
            )
        )

        for course in active_courses:

            while (
                academic_capacity_left(
                    current_day
                ) > 0
                and course_capacity_left(
                    current_day,
                    course,
                ) > 0
            ):

                relevant = [
                    item
                    for item in items
                    if (
                        item["course"]
                        == course
                        and item[
                            "remaining_minutes"
                        ] > 0
                        and current_day
                        <= item[
                            "deadline"
                        ]
                        and (
                            item["type"]
                            != "Project"
                            or current_day
                            >= project_ready_date(
                                item
                            )
                        )
                    )
                ]

                if not relevant:
                    break

                relevant.sort(
                    key=lambda item: (
                        -item_score(item),
                        item["deadline"],
                        item[
                            "remaining_minutes"
                        ],
                    )
                )

                item = relevant[0]

                desired = min(
                    item[
                        "remaining_minutes"
                    ],
                    item[
                        "max_block_minutes"
                    ],
                    course_capacity_left(
                        current_day,
                        course,
                    ),
                    academic_capacity_left(
                        current_day
                    ),
                )

                slot = find_slot(
                    current_day,
                    desired,
                    course,
                )

                if slot is None:
                    break

                (
                    start,
                    actual_minutes,
                ) = slot

                schedule_item = {
                    "name": item[
                        "name"
                    ],
                    "course": item[
                        "course"
                    ],
                    "type": item[
                        "type"
                    ],
                    "deadline": item[
                        "deadline"
                    ],
                    "source_id": item[
                        "id"
                    ],
                    "notes": item.get(
                        "notes",
                        "",
                    ),
                    "url": item.get(
                        "url",
                        "",
                    ),
                }

                create_work_and_break_blocks(
                    schedule_item,
                    current_day,
                    start,
                    actual_minutes,
                )

                item[
                    "remaining_minutes"
                ] -= actual_minutes

        current_day += timedelta(
            days=1
        )


# =========================================================
# TASK SCHEDULER
# =========================================================

def schedule_tasks():

    items = []

    for task in st.session_state.tasks:

        item = task.copy()

        item[
            "remaining_minutes"
        ] = task[
            "estimated_minutes"
        ]

        items.append(
            item
        )

    # Urgent first, shorter task wins ties.
    items.sort(
        key=lambda item: (
            -item_score(item),
            item[
                "remaining_minutes"
            ],
        )
    )

    for item in items:

        day = date.today()

        while (
            day <= item["deadline"]
            and item[
                "remaining_minutes"
            ] > 0
        ):

            free = (
                free_intervals_for_date(
                    day
                )
            )

            if not free:

                day += timedelta(
                    days=1
                )

                continue

            desired = min(
                item[
                    "remaining_minutes"
                ],
                item[
                    "max_block_minutes"
                ],
            )

            candidate = None

            for start, end in free:

                available = (
                    minutes_between(
                        start,
                        end,
                    )
                )

                if (
                    available
                    >= min(
                        desired,
                        item[
                            "remaining_minutes"
                        ],
                    )
                ):

                    candidate = (
                        start,
                        min(
                            desired,
                            available,
                        ),
                    )

                    break

                if (
                    available >= 10
                    and candidate
                    is None
                ):

                    candidate = (
                        start,
                        min(
                            desired,
                            available,
                        ),
                    )

            if candidate is None:

                day += timedelta(
                    days=1
                )

                continue

            (
                start,
                block_minutes,
            ) = candidate

            block_end = (
                start
                + timedelta(
                    minutes=block_minutes
                )
            )

            st.session_state.schedule.append(
                {
                    "name": item[
                        "name"
                    ],
                    "course": "",
                    "type": "Task",
                    "date": day,
                    "start": start,
                    "end": block_end,
                    "work_minutes": block_minutes,
                    "deadline": item[
                        "deadline"
                    ],
                    "source_id": item[
                        "id"
                    ],
                    "notes": item.get(
                        "notes",
                        "",
                    ),
                    "url": item.get(
                        "url",
                        "",
                    ),
                }
            )

            item[
                "remaining_minutes"
            ] -= block_minutes


# =========================================================
# REBUILD
# =========================================================

def rebuild_schedule():

    st.session_state.schedule = []

    # Learning first
    schedule_study_topics()

    # Then academic execution
    schedule_academic_work()

    # Then normal life tasks
    schedule_tasks()


# =========================================================
# CARD STYLING
# =========================================================

def hex_to_rgba(
    hex_color,
    alpha=0.10,
):

    hex_color = (
        hex_color.lstrip(
            "#"
        )
    )

    if len(hex_color) != 6:

        return (
            f"rgba(120,120,120,"
            f"{alpha})"
        )

    r = int(
        hex_color[0:2],
        16,
    )

    g = int(
        hex_color[2:4],
        16,
    )

    b = int(
        hex_color[4:6],
        16,
    )

    return (
        f"rgba("
        f"{r},"
        f"{g},"
        f"{b},"
        f"{alpha}"
        f")"
    )


def render_card(
    title,
    subtitle,
    start,
    end,
    item_type,
    color="#777777",
    notes="",
    url="",
):

    background = hex_to_rgba(
        color,
        0.10,
    )

    if notes:

        safe_notes = (
            notes
            .replace(
                "<",
                "&lt;",
            )
            .replace(
                ">",
                "&gt;",
            )
        )

        notes_html = (
            f'<div style="'
            f'margin-top:6px;'
            f'opacity:.76;'
            f'font-size:.78rem;'
            f'">'
            f'{safe_notes}'
            f'</div>'
        )

    else:

        notes_html = ""

    if url:

        link_html = (
            f'<div style="'
            f'margin-top:7px;'
            f'">'
            f'<a href="{url}" '
            f'target="_blank">'
            f'Open resource ↗'
            f'</a>'
            f'</div>'
        )

    else:

        link_html = ""

    html = (
        f'<div style="'
        f'border-left:5px solid {color};'
        f'background:{background};'
        f'padding:10px 12px;'
        f'margin:8px 0;'
        f'border-radius:9px;'
        f'">'

        f'<div style="'
        f'font-weight:700;'
        f'font-size:.98rem;'
        f'">'
        f'{title}'
        f'</div>'

        f'<div style="'
        f'opacity:.76;'
        f'font-size:.82rem;'
        f'margin-top:2px;'
        f'">'
        f'{subtitle}'
        f'</div>'

        f'<div style="'
        f'margin-top:6px;'
        f'font-size:.87rem;'
        f'">'
        f'{start.strftime("%I:%M %p")} '
        f'– '
        f'{end.strftime("%I:%M %p")}'
        f'</div>'

        f'<div style="'
        f'opacity:.65;'
        f'font-size:.76rem;'
        f'margin-top:3px;'
        f'">'
        f'{item_type}'
        f'</div>'

        f'{notes_html}'
        f'{link_html}'

        f'</div>'
    )

    st.markdown(
        html,
        unsafe_allow_html=True,
    )


# =========================================================
# PDF EXPORT
# =========================================================

def pdf_lines_for_day(day):

    lines = []

    for event in events_for_date(
        day
    ):

        if event.get(
            "location"
        ):

            location = (
                f" @ "
                f"{event['location']}"
            )

        else:

            location = ""

        lines.append(
            (
                event[
                    "actual_start"
                ],
                (
                    f"{event['actual_start'].strftime('%I:%M %p')}"
                    f"–"
                    f"{event['actual_end'].strftime('%I:%M %p')}"
                    f"  EVENT: "
                    f"{event['name']}"
                    f"{location}"
                ),
            )
        )

    for block in st.session_state.schedule:

        if block["date"] != day:
            continue

        if block["type"] == "Break":

            label = "BREAK"

        else:

            label = (
                f"{block['type'].upper()}: "
                f"{block['name']}"
            )

        if block.get(
            "course"
        ):

            label += (
                f" "
                f"({block['course']})"
            )

        lines.append(
            (
                block["start"],
                (
                    f"{block['start'].strftime('%I:%M %p')}"
                    f"–"
                    f"{block['end'].strftime('%I:%M %p')}"
                    f"  "
                    f"{label}"
                ),
            )
        )

    for reminder in st.session_state.reminders:

        if reminder["date"] == day:

            lines.append(
                (
                    combine(
                        day,
                        reminder[
                            "time"
                        ],
                    ),
                    (
                        f"{reminder['time'].strftime('%I:%M %p')}"
                        f"  REMINDER: "
                        f"{reminder['name']}"
                    ),
                )
            )

    return [
        text
        for _, text
        in sorted(
            lines,
            key=lambda item: item[
                0
            ],
        )
    ]


def build_week_pdf(
    week_dates,
):

    buffer = BytesIO()

    pdf = canvas.Canvas(
        buffer,
        pagesize=letter,
    )

    width, height = letter

    for day in week_dates:

        pdf.setFont(
            "Helvetica-Bold",
            18,
        )

        pdf.drawString(
            48,
            height - 55,
            day.strftime(
                "%A, %B %d, %Y"
            ),
        )

        pdf.setFont(
            "Helvetica",
            10,
        )

        y = height - 82

        windows = (
            work_windows_for_date(
                day
            )
        )

        if windows:

            window_text = ", ".join(
                (
                    f"{start.strftime('%I:%M %p')}"
                    f"–"
                    f"{end.strftime('%I:%M %p')}"
                )
                for start, end
                in windows
            )

            pdf.drawString(
                48,
                y,
                (
                    f"Work window(s): "
                    f"{window_text}"
                ),
            )

            y -= 20

        lines = (
            pdf_lines_for_day(
                day
            )
        )

        if not lines:

            pdf.setFillColor(
                colors.grey
            )

            pdf.drawString(
                48,
                y,
                "No scheduled items.",
            )

            pdf.setFillColor(
                colors.black
            )

            y -= 20

        else:

            for line in lines:

                if y < 180:

                    pdf.showPage()

                    pdf.setFont(
                        "Helvetica-Bold",
                        14,
                    )

                    pdf.drawString(
                        48,
                        height - 55,
                        (
                            f"{day.strftime('%A')} "
                            f"— continued"
                        ),
                    )

                    pdf.setFont(
                        "Helvetica",
                        10,
                    )

                    y = height - 82

                pdf.drawString(
                    48,
                    y,
                    line[:110],
                )

                y -= 17

        y -= 8

        pdf.setFont(
            "Helvetica-Bold",
            11,
        )

        pdf.drawString(
            48,
            y,
            "Notes",
        )

        y -= 16

        pdf.setStrokeColor(
            colors.lightgrey
        )

        for _ in range(8):

            pdf.line(
                48,
                y,
                width - 48,
                y,
            )

            y -= 24

        pdf.setStrokeColor(
            colors.black
        )

        pdf.showPage()

    pdf.save()

    buffer.seek(0)

    return buffer.getvalue()


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.header(
        "Planner Setup"
    )

    st.caption(
        "Use the sidebar arrow to collapse this panel "
        "whenever you want more calendar space."
    )

    # =====================================================
    # COURSES
    # =====================================================

    st.subheader(
        "1. Courses"
    )

    new_course_name = (
        st.text_input(
            "Course name",
            placeholder="Biology",
            key="new_course_name",
        )
    )

PRESET_COLORS = {
    "Blue": "#4F8EF7",
    "Green": "#4CAF50",
    "Purple": "#9C6ADE",
    "Orange": "#F59E0B",
    "Red": "#EF5350",
    "Pink": "#EC4899",
}

if "new_course_color" not in st.session_state:
    st.session_state.new_course_color = "#4F8EF7"

st.caption("Quick colors")

preset_cols = st.columns(6)

for index, (color_name, hex_color) in enumerate(PRESET_COLORS.items()):

    with preset_cols[index]:

        st.markdown(
            f"""
            <div style="
                width:100%;
                height:18px;
                border-radius:6px;
                background:{hex_color};
                margin-bottom:4px;
            "></div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            "●",
            key=f"preset_color_{color_name}",
            help=color_name,
            use_container_width=True,
        ):
            st.session_state.new_course_color = hex_color
            st.rerun()

new_course_color = st.color_picker(
    "Custom color",
    value=st.session_state.new_course_color,
    key="course_color_picker",
)

st.session_state.new_course_color = new_course_color

if st.button(
    "Add Course",
    use_container_width=True,
    key="add_course_button",
):
        cleaned = (
            new_course_name.strip()
        )

        existing = [
            course["name"].lower()
            for course
            in st.session_state.courses
        ]

        if not cleaned:

            st.error(
                "Enter a course name."
            )

        elif cleaned.lower() in existing:

            st.error(
                "That course already exists."
            )

        else:

            st.session_state.courses.append(
                {
                    "id": next_id(
                        st.session_state.courses
                    ),
                    "name": cleaned,
                    "color": (
                        new_course_color
                    ),
                }
            )

            st.rerun()

    if st.session_state.courses:

        for course in st.session_state.courses:

            st.markdown(
                (
                    f'<div style="'
                    f'display:flex;'
                    f'align-items:center;'
                    f'gap:8px;'
                    f'margin:5px 0;'
                    f'">'

                    f'<div style="'
                    f'width:14px;'
                    f'height:14px;'
                    f'border-radius:4px;'
                    f'background:'
                    f'{course["color"]};'
                    f'">'
                    f'</div>'

                    f'<span>'
                    f'{course["name"]}'
                    f'</span>'

                    f'</div>'
                ),
                unsafe_allow_html=True,
            )

    else:

        st.info(
            "Add at least one course "
            "for academic planning."
        )

    st.divider()

    # =====================================================
    # WORK HOURS
    # =====================================================

    st.subheader(
        "2. Work Hours"
    )

    st.caption(
        "Flexible work is only placed "
        "inside these windows."
    )

    c1, c2, c3 = st.columns(
        3
    )

    with c1:

        if st.button(
            "Weekdays",
            key="weekdays_shortcut",
            use_container_width=True,
        ):

            st.session_state.work_days_picker = (
                WEEKDAYS.copy()
            )

            st.rerun()

    with c2:

        if st.button(
            "Every Day",
            key="everyday_shortcut",
            use_container_width=True,
        ):

            st.session_state.work_days_picker = (
                DAYS.copy()
            )

            st.rerun()

    with c3:

        if st.button(
            "Clear",
            key="clear_days_shortcut",
            use_container_width=True,
        ):

            st.session_state.work_days_picker = []

            st.rerun()

    selected_work_days = (
        st.multiselect(
            "Work days",
            DAYS,
            key="work_days_picker",
        )
    )

    work_start = (
        st.time_input(
            "Start",
            value=time(
                17,
                0,
            ),
            key="work_window_start",
        )
    )

    work_end = (
        st.time_input(
            "End",
            value=time(
                21,
                0,
            ),
            key="work_window_end",
        )
    )

    if st.button(
        "Add Work Window",
        use_container_width=True,
        key="add_work_window",
    ):

        if not selected_work_days:

            st.error(
                "Choose at least one day."
            )

        elif work_end <= work_start:

            st.error(
                "End must be after start."
            )

        else:

            st.session_state.work_windows.append(
                {
                    "id": next_id(
                        st.session_state.work_windows
                    ),
                    "days": (
                        selected_work_days.copy()
                    ),
                    "start_time": (
                        work_start
                    ),
                    "end_time": (
                        work_end
                    ),
                }
            )

            rebuild_schedule()

            st.rerun()

    if not st.session_state.work_windows:

        st.warning(
            "Create at least one work window "
            "before scheduling flexible work."
        )

    st.divider()

    # =====================================================
    # PLANNER PREFERENCES
    # =====================================================

    st.subheader(
        "3. Planner Preferences"
    )

    if not st.session_state.show_preferences:

        if st.button(
            "Edit Planner Preferences",
            use_container_width=True,
            key="edit_preferences_button",
        ):

            st.session_state.show_preferences = True

            st.rerun()

    else:

        include_breaks = (
            st.checkbox(
                "Include breaks during long work sessions",
                value=(
                    st.session_state.include_breaks
                ),
                key="pref_include_breaks",
            )
        )

        if include_breaks:

            break_after = (
                st.number_input(
                    "Work before taking a break (minutes)",
                    min_value=30,
                    max_value=180,
                    value=(
                        st.session_state
                        .break_after_minutes
                    ),
                    step=15,
                    key="pref_break_after",
                )
            )

            break_length = (
                st.number_input(
                    "Break length (minutes)",
                    min_value=5,
                    max_value=60,
                    value=(
                        st.session_state
                        .break_length_minutes
                    ),
                    step=5,
                    key="pref_break_length",
                )
            )

        else:

            break_after = (
                st.session_state
                .break_after_minutes
            )

            break_length = (
                st.session_state
                .break_length_minutes
            )

        preferred_study = (
            st.number_input(
                "Typical study block (minutes)",
                min_value=30,
                max_value=180,
                value=(
                    st.session_state
                    .preferred_study_minutes
                ),
                step=15,
                key="pref_study_session",
                help=(
                    "The planner aims for this "
                    "size when it creates a "
                    "normal study block."
                ),
            )
        )

        max_study = (
            st.number_input(
                "Longest study block (minutes)",
                min_value=30,
                max_value=240,
                value=(
                    st.session_state
                    .max_study_minutes
                ),
                step=15,
                key="pref_max_study",
                help=(
                    "A single study topic will "
                    "not exceed this length "
                    "in one sitting."
                ),
            )
        )

        daily_academic_cap = (
            st.number_input(
                "Daily schoolwork limit (minutes)",
                min_value=60,
                max_value=720,
                value=(
                    st.session_state
                    .daily_academic_cap
                ),
                step=30,
                key="pref_daily_academic_cap",
                help=(
                    "Maximum total studying, "
                    "assignments, and project "
                    "work per day across all "
                    "courses."
                ),
            )
        )

        use_course_cap = (
            st.checkbox(
                "Limit how much time one course can use per day",
                value=(
                    st.session_state
                    .use_course_cap
                ),
                key="pref_use_course_cap",
            )
        )

        if use_course_cap:

            course_cap = (
                st.number_input(
                    "Daily limit for one course (minutes)",
                    min_value=30,
                    max_value=480,
                    value=(
                        st.session_state
                        .daily_course_cap
                    ),
                    step=30,
                    key="pref_course_cap",
                    help=(
                        "The scheduler stays on "
                        "a course until this "
                        "daily limit is reached, "
                        "then moves to another course."
                    ),
                )
            )

        else:

            course_cap = (
                st.session_state
                .daily_course_cap
            )

        if st.button(
            "Save Preferences",
            use_container_width=True,
            key="save_preferences",
        ):

            if preferred_study > max_study:

                st.error(
                    "Typical study block cannot "
                    "be longer than the longest "
                    "study block."
                )

            else:

                st.session_state.include_breaks = (
                    include_breaks
                )

                st.session_state.break_after_minutes = int(
                    break_after
                )

                st.session_state.break_length_minutes = int(
                    break_length
                )

                st.session_state.preferred_study_minutes = int(
                    preferred_study
                )

                st.session_state.max_study_minutes = int(
                    max_study
                )

                st.session_state.daily_academic_cap = int(
                    daily_academic_cap
                )

                st.session_state.use_course_cap = (
                    use_course_cap
                )

                st.session_state.daily_course_cap = int(
                    course_cap
                )

                st.session_state.show_preferences = False

                rebuild_schedule()

                st.rerun()

    st.divider()

    # =====================================================
    # ADD TO PLANNER
    # =====================================================

    st.subheader(
        "4. Add to Planner"
    )

    item_type = (
        st.radio(
            "Type",
            [
                "Study Topic",
                "Assignment",
                "Project",
                "Event",
                "Task",
                "Reminder",
            ],
            key="item_type_picker",
        )
    )

    course_names = [
        course["name"]
        for course
        in st.session_state.courses
    ]

    # =====================================================
    # STUDY TOPIC
    # =====================================================

    if item_type == "Study Topic":

        topic_name = (
            st.text_input(
                "Topic",
                placeholder=(
                    "Object-Oriented Programming"
                ),
                key="topic_name",
            )
        )

        if course_names:

            topic_course = (
                st.selectbox(
                    "Course",
                    course_names,
                    key="topic_course",
                )
            )

        else:

            topic_course = None

            st.warning(
                "Add a course before saving "
                "a study topic."
            )

        projects = [
            item
            for item
            in st.session_state.academic_work
            if (
                item["type"]
                == "Project"
                and (
                    topic_course is None
                    or item["course"]
                    == topic_course
                )
            )
        ]

        project_options = {
            "None": None,
            **{
                project["name"]:
                project["id"]
                for project in projects
            },
        }

        linked_project_name = (
            st.selectbox(
                "Related project",
                list(
                    project_options.keys()
                ),
                key="topic_linked_project",
            )
        )

        linked_project_id = (
            project_options[
                linked_project_name
            ]
        )

        default_deadline = (
            date.today()
            + timedelta(
                days=7
            )
        )

        if linked_project_id is not None:

            project = next(
                item
                for item in projects
                if (
                    item["id"]
                    == linked_project_id
                )
            )

            default_deadline = (
                project[
                    "deadline"
                ]
            )

        topic_deadline = (
            st.date_input(
                "Learn by",
                value=default_deadline,
                key="topic_deadline",
            )
        )

        familiarity = (
            st.selectbox(
                "Familiarity",
                [
                    "Never seen it",
                    "Some exposure",
                    "Comfortable",
                    "Review only",
                ],
                key="topic_familiarity",
            )
        )

        difficulty = (
            st.selectbox(
                "Difficulty",
                [
                    "Easy",
                    "Medium",
                    "Hard",
                ],
                key="topic_difficulty",
            )
        )

        goal = (
            st.selectbox(
                "Goal",
                [
                    "Understand the basics",
                    "Complete practice problems",
                    "Use it in a project",
                    "Prepare for a test",
                ],
                key="topic_goal",
            )
        )

        topic_priority = (
            st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="topic_priority",
            )
        )

        topic_max_session = (
            st.number_input(
                "Longest session for this topic",
                min_value=30,
                max_value=240,
                value=(
                    st.session_state
                    .max_study_minutes
                ),
                step=15,
                key="topic_max_session",
            )
        )

        topic_notes = (
            st.text_area(
                "Notes / details",
                key="topic_notes",
            )
        )

        topic_url = (
            st.text_input(
                "Resource link (optional)",
                placeholder="https://...",
                key="topic_url",
            )
        )

        recommended_minutes = (
            calculate_study_time(
                difficulty,
                familiarity,
                goal,
            )
        )

        st.metric(
            "Recommended study time",
            format_minutes(
                recommended_minutes
            ),
        )

        if st.button(
            "Add Study Topic",
            use_container_width=True,
            key="add_topic",
        ):

            if not st.session_state.work_windows:

                st.error(
                    "Add at least one "
                    "work window first."
                )

            elif not topic_course:

                st.error(
                    "Add at least one "
                    "course first."
                )

            elif not topic_name.strip():

                st.error(
                    "Enter a topic."
                )

            else:

                topic_id = next_id(
                    st.session_state.study_topics
                )

                st.session_state.study_topics.append(
                    {
                        "id": topic_id,
                        "topic": (
                            topic_name.strip()
                        ),
                        "name": (
                            topic_name.strip()
                        ),
                        "course": topic_course,
                        "deadline": (
                            topic_deadline
                        ),
                        "recommended_minutes": (
                            recommended_minutes
                        ),
                        "priority": (
                            topic_priority
                        ),
                        "max_session_minutes": int(
                            topic_max_session
                        ),
                        "linked_project_id": (
                            linked_project_id
                        ),
                        "familiarity": (
                            familiarity
                        ),
                        "difficulty": (
                            difficulty
                        ),
                        "goal": goal,
                        "notes": (
                            topic_notes.strip()
                        ),
                        "url": (
                            topic_url.strip()
                        ),
                    }
                )

                if linked_project_id is not None:

                    for project in st.session_state.academic_work:

                        if (
                            project["id"]
                            == linked_project_id
                            and topic_id
                            not in project[
                                "linked_topic_ids"
                            ]
                        ):

                            project[
                                "linked_topic_ids"
                            ].append(
                                topic_id
                            )

                rebuild_schedule()

                st.rerun()

    # =====================================================
    # ASSIGNMENT / PROJECT
    # =====================================================

    elif item_type in {
        "Assignment",
        "Project",
    }:

        work_name = (
            st.text_input(
                item_type,
                placeholder=(
                    "Research Paper"
                    if item_type
                    == "Assignment"
                    else "Python Project"
                ),
                key="academic_work_name",
            )
        )

        if course_names:

            work_course = (
                st.selectbox(
                    "Course",
                    course_names,
                    key="academic_work_course",
                )
            )

        else:

            work_course = None

            st.warning(
                "Add a course before saving "
                "academic work."
            )

        work_due = (
            st.date_input(
                "Due date",
                value=(
                    date.today()
                    + timedelta(
                        days=7
                    )
                ),
                key="academic_work_due",
            )
        )

        hours = (
            st.number_input(
                "Estimated hours",
                min_value=0,
                max_value=100,
                value=2,
                key="academic_work_hours",
            )
        )

        mins = (
            st.number_input(
                "Additional minutes",
                min_value=0,
                max_value=59,
                value=0,
                key="academic_work_minutes",
            )
        )

        work_priority = (
            st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="academic_work_priority",
            )
        )

        max_block = (
            st.number_input(
                "Longest single work block",
                min_value=30,
                max_value=480,
                value=180,
                step=30,
                key="academic_work_max_block",
            )
        )

        allow_due_day = (
            st.checkbox(
                "Allow work on due date",
                value=True,
                key="academic_work_allow_due",
            )
        )

        work_notes = (
            st.text_area(
                "Notes / details",
                key="academic_work_notes",
            )
        )

        work_url = (
            st.text_input(
                "Resource link (optional)",
                placeholder="https://...",
                key="academic_work_url",
            )
        )

        if st.button(
            f"Add {item_type}",
            use_container_width=True,
            key="add_academic_work",
        ):

            total = (
                hours * 60
                + mins
            )

            if not st.session_state.work_windows:

                st.error(
                    "Add at least one "
                    "work window first."
                )

            elif not work_course:

                st.error(
                    "Add at least one "
                    "course first."
                )

            elif not work_name.strip():

                st.error(
                    f"Enter a "
                    f"{item_type.lower()} "
                    f"name."
                )

            elif total <= 0:

                st.error(
                    "Estimated time must "
                    "be greater than zero."
                )

            else:

                st.session_state.academic_work.append(
                    {
                        "id": next_id(
                            st.session_state.academic_work
                        ),
                        "name": (
                            work_name.strip()
                        ),
                        "course": (
                            work_course
                        ),
                        "type": item_type,
                        "deadline": (
                            work_due
                        ),
                        "estimated_minutes": int(
                            total
                        ),
                        "priority": (
                            work_priority
                        ),
                        "max_block_minutes": int(
                            max_block
                        ),
                        "allow_deadline_day": (
                            allow_due_day
                        ),
                        "linked_topic_ids": [],
                        "notes": (
                            work_notes.strip()
                        ),
                        "url": (
                            work_url.strip()
                        ),
                    }
                )

                rebuild_schedule()

                st.rerun()

    # =====================================================
    # EVENT
    # =====================================================

    elif item_type == "Event":

        event_name = (
            st.text_input(
                "Event",
                placeholder="Biology lecture",
                key="event_name",
            )
        )

        recurring = (
            st.checkbox(
                "Repeats weekly",
                key="event_recurring",
            )
        )

        if recurring:

            event_days = (
                st.multiselect(
                    "Days",
                    DAYS,
                    key="event_days",
                )
            )

            event_date = None

        else:

            event_date = (
                st.date_input(
                    "Date",
                    key="event_date",
                )
            )

            event_days = []

        start_time = (
            st.time_input(
                "Start time",
                value=time(
                    11,
                    0,
                ),
                key="event_start",
            )
        )

        end_time = (
            st.time_input(
                "End time",
                value=time(
                    12,
                    30,
                ),
                key="event_end",
            )
        )

        event_location = (
            st.text_input(
                "Location",
                placeholder=(
                    "BLDG X, Room 204"
                ),
                key="event_location",
            )
        )

        b1, b2 = st.columns(
            2
        )

        with b1:

            buffer_before = (
                st.number_input(
                    "Travel/setup before (min)",
                    min_value=0,
                    max_value=180,
                    value=0,
                    step=5,
                    key="event_buffer_before",
                )
            )

        with b2:

            buffer_after = (
                st.number_input(
                    "Travel/wrap-up after (min)",
                    min_value=0,
                    max_value=180,
                    value=0,
                    step=5,
                    key="event_buffer_after",
                )
            )

        event_notes = (
            st.text_area(
                "Notes / details",
                key="event_notes",
            )
        )

        event_url = (
            st.text_input(
                "Event link (optional)",
                placeholder="https://...",
                key="event_url",
            )
        )

        if st.button(
            "Add Event",
            use_container_width=True,
            key="add_event",
        ):

            if not event_name.strip():

                st.error(
                    "Enter an event."
                )

            elif end_time <= start_time:

                st.error(
                    "End time must be "
                    "after start time."
                )

            elif (
                recurring
                and not event_days
            ):

                st.error(
                    "Select at least "
                    "one day."
                )

            else:

                st.session_state.events.append(
                    {
                        "id": next_id(
                            st.session_state.events
                        ),
                        "name": (
                            event_name.strip()
                        ),
                        "recurring": (
                            recurring
                        ),
                        "days": event_days,
                        "date": event_date,
                        "start_time": (
                            start_time
                        ),
                        "end_time": (
                            end_time
                        ),
                        "location": (
                            event_location.strip()
                        ),
                        "buffer_before": int(
                            buffer_before
                        ),
                        "buffer_after": int(
                            buffer_after
                        ),
                        "notes": (
                            event_notes.strip()
                        ),
                        "url": (
                            event_url.strip()
                        ),
                    }
                )

                rebuild_schedule()

                st.rerun()

    # =====================================================
    # TASK
    # =====================================================

    elif item_type == "Task":

        task_name = (
            st.text_input(
                "Task",
                placeholder=(
                    "Grocery shopping"
                ),
                key="task_name",
            )
        )

        task_deadline = (
            st.date_input(
                "Complete by",
                value=(
                    date.today()
                    + timedelta(
                        days=3
                    )
                ),
                key="task_deadline",
            )
        )

        task_hours = (
            st.number_input(
                "Hours",
                min_value=0,
                max_value=24,
                value=1,
                key="task_hours",
            )
        )

        task_minutes = (
            st.number_input(
                "Additional minutes",
                min_value=0,
                max_value=59,
                value=0,
                key="task_minutes",
            )
        )

        task_priority = (
            st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="task_priority",
            )
        )

        task_max_block = (
            st.number_input(
                "Longest single block",
                min_value=10,
                max_value=480,
                value=120,
                step=10,
                key="task_max_block",
            )
        )

        task_notes = (
            st.text_area(
                "Notes / details",
                key="task_notes",
            )
        )

        task_url = (
            st.text_input(
                "Link (optional)",
                placeholder="https://...",
                key="task_url",
            )
        )

        if st.button(
            "Add Task",
            use_container_width=True,
            key="add_task",
        ):

            total = (
                task_hours * 60
                + task_minutes
            )

            if not st.session_state.work_windows:

                st.error(
                    "Add at least one "
                    "work window first."
                )

            elif not task_name.strip():

                st.error(
                    "Enter a task."
                )

            elif total <= 0:

                st.error(
                    "Estimated time must "
                    "be greater than zero."
                )

            else:

                st.session_state.tasks.append(
                    {
                        "id": next_id(
                            st.session_state.tasks
                        ),
                        "name": (
                            task_name.strip()
                        ),
                        "deadline": (
                            task_deadline
                        ),
                        "estimated_minutes": int(
                            total
                        ),
                        "priority": (
                            task_priority
                        ),
                        "max_block_minutes": int(
                            task_max_block
                        ),
                        "notes": (
                            task_notes.strip()
                        ),
                        "url": (
                            task_url.strip()
                        ),
                    }
                )

                rebuild_schedule()

                st.rerun()

    # =====================================================
    # REMINDER
    # =====================================================

    elif item_type == "Reminder":

        reminder_name = (
            st.text_input(
                "Reminder",
                placeholder=(
                    "Switch laundry"
                ),
                key="reminder_name",
            )
        )

        reminder_date = (
            st.date_input(
                "Date",
                key="reminder_date",
            )
        )

        reminder_time = (
            st.time_input(
                "Time",
                value=time(
                    18,
                    0,
                ),
                key="reminder_time",
            )
        )

        reserve_time = (
            st.checkbox(
                "Reserve time",
                key="reminder_reserve",
            )
        )

        reserve_minutes = 0

        if reserve_time:

            reserve_minutes = (
                st.number_input(
                    "Minutes",
                    min_value=5,
                    max_value=120,
                    value=10,
                    step=5,
                    key="reminder_minutes",
                )
            )

        reminder_notes = (
            st.text_area(
                "Notes",
                key="reminder_notes",
            )
        )

        reminder_url = (
            st.text_input(
                "Link (optional)",
                placeholder="https://...",
                key="reminder_url",
            )
        )

        if st.button(
            "Add Reminder",
            use_container_width=True,
            key="add_reminder",
        ):

            if not reminder_name.strip():

                st.error(
                    "Enter a reminder."
                )

            else:

                st.session_state.reminders.append(
                    {
                        "id": next_id(
                            st.session_state.reminders
                        ),
                        "name": (
                            reminder_name.strip()
                        ),
                        "date": (
                            reminder_date
                        ),
                        "time": (
                            reminder_time
                        ),
                        "reserve_minutes": int(
                            reserve_minutes
                        ),
                        "notes": (
                            reminder_notes.strip()
                        ),
                        "url": (
                            reminder_url.strip()
                        ),
                    }
                )

                rebuild_schedule()

                st.rerun()


# =========================================================
# WEEK CONTROLS
# =========================================================

left, center, right = (
    st.columns(
        [
            1,
            3,
            1,
        ]
    )
)

with left:

    if st.button(
        "← Previous Week",
        key="previous_week",
    ):

        st.session_state.week_offset -= 1

        st.rerun()


with center:

    week_dates = (
        get_visible_week()
    )

    st.subheader(
        f"{week_dates[0].strftime('%b %d')} "
        f"– "
        f"{week_dates[-1].strftime('%b %d, %Y')}"
    )


with right:

    if st.button(
        "Next Week →",
        key="next_week",
    ):

        st.session_state.week_offset += 1

        st.rerun()


b1, b2, b3 = st.columns(
    3
)


with b1:

    if st.button(
        "🔄 Regenerate Schedule",
        use_container_width=True,
        key="regen_schedule",
    ):

        rebuild_schedule()

        st.rerun()


with b2:

    if st.button(
        "Today",
        use_container_width=True,
        key="return_today",
    ):

        st.session_state.week_offset = 0

        st.rerun()


with b3:

    pdf_bytes = build_week_pdf(
        get_visible_week()
    )

    st.download_button(
        "🖨️ Download weekly PDF",
        data=pdf_bytes,
        file_name=(
            f"study_schedule_"
            f"{week_dates[0].isoformat()}"
            f".pdf"
        ),
        mime="application/pdf",
        use_container_width=True,
        key="download_schedule_pdf",
    )


st.divider()


# =========================================================
# SUMMARY
# =========================================================

week_dates = (
    get_visible_week()
)

scheduled_academic = sum(
    block["work_minutes"]
    for block
    in st.session_state.schedule
    if (
        block["date"]
        in week_dates
        and block["type"]
        in {
            "Study",
            "Assignment",
            "Project",
        }
    )
)

available_minutes = sum(
    minutes_between(
        start,
        end,
    )
    for day in week_dates
    for start, end
    in work_windows_for_date(
        day
    )
)

s1, s2, s3 = (
    st.columns(3)
)

s1.metric(
    "Academic work scheduled",
    format_minutes(
        scheduled_academic
    ),
)

s2.metric(
    "Work-window time",
    format_minutes(
        available_minutes
    ),
)

s3.metric(
    "Courses",
    len(
        st.session_state.courses
    ),
)


st.divider()


# =========================================================
# CALENDAR
# =========================================================

def render_day(day):

    st.markdown(
        f"### {day.strftime('%A')}"
    )

    st.caption(
        day.strftime(
            "%B %d"
        )
    )

    for (
        start,
        end,
    ) in work_windows_for_date(
        day
    ):

        st.caption(
            f"🕒 Work window "
            f"{start.strftime('%I:%M %p')} "
            f"– "
            f"{end.strftime('%I:%M %p')}"
        )

    calendar_items = []

    for event in events_for_date(
        day
    ):

        calendar_items.append(
            {
                "name": event[
                    "name"
                ],
                "course": "",
                "type": "Event",
                "start": event[
                    "actual_start"
                ],
                "end": event[
                    "actual_end"
                ],
                "location": event.get(
                    "location",
                    "",
                ),
                "notes": event.get(
                    "notes",
                    "",
                ),
                "url": event.get(
                    "url",
                    "",
                ),
                "buffer_before": (
                    minutes_between(
                        event[
                            "blocked_start"
                        ],
                        event[
                            "actual_start"
                        ],
                    )
                ),
                "buffer_after": (
                    minutes_between(
                        event[
                            "actual_end"
                        ],
                        event[
                            "blocked_end"
                        ],
                    )
                ),
            }
        )

    for block in st.session_state.schedule:

        if block["date"] == day:

            calendar_items.append(
                block
            )

    calendar_items.sort(
        key=lambda item: item[
            "start"
        ]
    )

    for item in calendar_items:

        if item["type"] == "Break":

            st.caption(
                f"☕ "
                f"{item['start'].strftime('%I:%M %p')} "
                f"– "
                f"{item['end'].strftime('%I:%M %p')} "
                f"Break"
            )

            continue

        icon = {
            "Study": "📚",
            "Assignment": "📝",
            "Project": "🛠️",
            "Task": "✅",
            "Event": "📅",
        }.get(
            item["type"],
            "•",
        )

        course = item.get(
            "course",
            "",
        )

        if course:

            color = course_color(
                course
            )

            subtitle = course

        else:

            color = "#777777"

            subtitle = (
                item["type"]
            )

        if (
            item["type"] == "Event"
            and item.get(
                "location"
            )
        ):

            subtitle = (
                f"{subtitle} • "
                f"{item['location']}"
            )

        render_card(
            title=(
                f"{icon} "
                f"{item['name']}"
            ),
            subtitle=subtitle,
            start=item["start"],
            end=item["end"],
            item_type=item[
                "type"
            ],
            color=color,
            notes=item.get(
                "notes",
                "",
            ),
            url=item.get(
                "url",
                "",
            ),
        )

        if item["type"] == "Event":

            before = item.get(
                "buffer_before",
                0,
            )

            after = item.get(
                "buffer_after",
                0,
            )

            if before or after:

                parts = []

                if before:

                    parts.append(
                        f"{before}m before"
                    )

                if after:

                    parts.append(
                        f"{after}m after"
                    )

                st.caption(
                    "🚶 Travel/setup buffer: "
                    + " • ".join(
                        parts
                    )
                )

    reminders = [
        reminder
        for reminder
        in st.session_state.reminders
        if reminder["date"]
        == day
    ]

    reminders.sort(
        key=lambda item: item[
            "time"
        ]
    )

    for reminder in reminders:

        text = (
            f"🔔 **"
            f"{reminder['time'].strftime('%I:%M %p')} "
            f"— "
            f"{reminder['name']}"
            f"**"
        )

        if reminder.get(
            "url"
        ):

            text += (
                f"  "
                f"[Open ↗]"
                f"({reminder['url']})"
            )

        st.markdown(
            text
        )

        if reminder.get(
            "notes"
        ):

            st.caption(
                reminder[
                    "notes"
                ]
            )

    # Deadlines
    for work in st.session_state.academic_work:

        if work["deadline"] == day:

            color = course_color(
                work[
                    "course"
                ]
            )

            st.markdown(
                (
                    f'<div style="'
                    f'border-left:4px solid {color};'
                    f'padding-left:8px;'
                    f'margin-top:8px;'
                    f'">'

                    f'<b>'
                    f'🚨 Due: '
                    f'{work["name"]}'
                    f'</b>'

                    f'<br>'

                    f'<span style="'
                    f'opacity:.7'
                    f'">'
                    f'{work["course"]}'
                    f'</span>'

                    f'</div>'
                ),
                unsafe_allow_html=True,
            )


# =========================================================
# WEEK DISPLAY
# =========================================================

row1 = st.columns(
    4
)

for index in range(4):

    with row1[index]:

        render_day(
            week_dates[
                index
            ]
        )


st.write("")


row2 = st.columns(
    3
)

for index in range(3):

    with row2[index]:

        render_day(
            week_dates[
                index + 4
            ]
        )


# =========================================================
# SCHEDULE CHECK
# =========================================================

st.divider()

st.header(
    "Schedule Check"
)

warnings = []


def scheduled_minutes(
    source_id,
    item_type,
):

    return sum(
        block[
            "work_minutes"
        ]
        for block
        in st.session_state.schedule
        if (
            block.get(
                "source_id"
            )
            == source_id
            and block[
                "type"
            ]
            == item_type
        )
    )


for topic in st.session_state.study_topics:

    actual = scheduled_minutes(
        topic["id"],
        "Study",
    )

    missing = (
        topic[
            "recommended_minutes"
        ]
        - actual
    )

    if missing > 0:

        warnings.append(
            f"{topic['course']} — "
            f"{topic['topic']} needs "
            f"{format_minutes(missing)} "
            f"more study time before "
            f"{topic['deadline'].strftime('%b %d')}."
        )


for work in st.session_state.academic_work:

    actual = scheduled_minutes(
        work["id"],
        work["type"],
    )

    missing = (
        work[
            "estimated_minutes"
        ]
        - actual
    )

    if missing > 0:

        warnings.append(
            f"{work['course']} — "
            f"{work['name']} needs "
            f"{format_minutes(missing)} "
            f"more work time before "
            f"{work['deadline'].strftime('%b %d')}."
        )


for task in st.session_state.tasks:

    actual = scheduled_minutes(
        task["id"],
        "Task",
    )

    missing = (
        task[
            "estimated_minutes"
        ]
        - actual
    )

    if missing > 0:

        warnings.append(
            f"{task['name']} needs "
            f"{format_minutes(missing)} "
            f"more time before "
            f"{task['deadline'].strftime('%b %d')}."
        )


if warnings:

    st.warning(
        "⚠️ Some work does not fit "
        "into the current schedule."
    )

    for warning in warnings:

        st.write(
            f"• {warning}"
        )

elif (
    st.session_state.study_topics
    or st.session_state.academic_work
    or st.session_state.tasks
):

    st.success(
        "Everything currently fits."
    )

else:

    st.info(
        "Add coursework or tasks "
        "to generate a schedule."
    )


# =========================================================
# MANAGE PLANNER
# =========================================================

st.divider()

st.header(
    "Manage Planner"
)

tabs = st.tabs(
    [
        "Courses",
        "Study",
        "Assignments & Projects",
        "Tasks",
        "Events",
        "Reminders",
        "Work Hours",
    ]
)


# =========================================================
# COURSES
# =========================================================

with tabs[0]:

    if not st.session_state.courses:

        st.info(
            "No courses yet."
        )

    for index, course in enumerate(
        st.session_state.courses
    ):

        c1, c2 = st.columns(
            [
                4,
                1,
            ]
        )

        with c1:

            new_color = (
                st.color_picker(
                    course["name"],
                    course["color"],
                    key=(
                        f"edit_course_color_"
                        f"{course['id']}"
                    ),
                )
            )

            if (
                new_color
                != course["color"]
            ):

                course["color"] = (
                    new_color
                )

        with c2:

            if st.button(
                "Delete",
                key=(
                    f"delete_course_"
                    f"{course['id']}"
                ),
            ):

                course_used = (
                    any(
                        topic[
                            "course"
                        ]
                        == course[
                            "name"
                        ]
                        for topic
                        in st.session_state.study_topics
                    )
                    or any(
                        item[
                            "course"
                        ]
                        == course[
                            "name"
                        ]
                        for item
                        in st.session_state.academic_work
                    )
                )

                if course_used:

                    st.error(
                        "Delete that course's "
                        "academic items first."
                    )

                else:

                    st.session_state.courses.pop(
                        index
                    )

                    st.rerun()


# =========================================================
# STUDY
# =========================================================

with tabs[1]:

    if not st.session_state.study_topics:

        st.info(
            "No study topics."
        )

    for topic in st.session_state.study_topics:

        with st.expander(
            f"{topic['course']} "
            f"— "
            f"{topic['topic']}"
        ):

            st.write(
                f"Recommended: "
                f"{format_minutes(topic['recommended_minutes'])}"
            )

            st.write(
                f"Learn by: "
                f"{topic['deadline'].strftime('%B %d, %Y')}"
            )

            st.write(
                f"Priority: "
                f"{topic['priority']}"
            )

            if topic.get(
                "notes"
            ):

                st.write(
                    topic[
                        "notes"
                    ]
                )

            if topic.get(
                "url"
            ):

                st.markdown(
                    f"[Open resource ↗]"
                    f"({topic['url']})"
                )

            if st.button(
                "Delete Topic",
                key=(
                    f"delete_topic_"
                    f"{topic['id']}"
                ),
            ):

                topic_id = (
                    topic["id"]
                )

                st.session_state.study_topics = [
                    item
                    for item
                    in st.session_state.study_topics
                    if (
                        item["id"]
                        != topic_id
                    )
                ]

                for work in st.session_state.academic_work:

                    if (
                        topic_id
                        in work[
                            "linked_topic_ids"
                        ]
                    ):

                        work[
                            "linked_topic_ids"
                        ].remove(
                            topic_id
                        )

                rebuild_schedule()

                st.rerun()


# =========================================================
# ASSIGNMENTS & PROJECTS
# =========================================================

with tabs[2]:

    if not st.session_state.academic_work:

        st.info(
            "No assignments or projects."
        )

    for item in st.session_state.academic_work:

        with st.expander(
            f"{item['course']} "
            f"— "
            f"{item['name']}"
        ):

            st.write(
                f"Type: "
                f"{item['type']}"
            )

            st.write(
                f"Estimated: "
                f"{format_minutes(item['estimated_minutes'])}"
            )

            st.write(
                f"Due: "
                f"{item['deadline'].strftime('%B %d, %Y')}"
            )

            st.write(
                f"Priority: "
                f"{item['priority']}"
            )

            if item.get(
                "notes"
            ):

                st.write(
                    item[
                        "notes"
                    ]
                )

            if item.get(
                "url"
            ):

                st.markdown(
                    f"[Open resource ↗]"
                    f"({item['url']})"
                )

            if st.button(
                "Delete",
                key=(
                    f"delete_work_"
                    f"{item['id']}"
                ),
            ):

                item_id = (
                    item["id"]
                )

                st.session_state.academic_work = [
                    work
                    for work
                    in st.session_state.academic_work
                    if (
                        work["id"]
                        != item_id
                    )
                ]

                for topic in st.session_state.study_topics:

                    if (
                        topic.get(
                            "linked_project_id"
                        )
                        == item_id
                    ):

                        topic[
                            "linked_project_id"
                        ] = None

                rebuild_schedule()

                st.rerun()


# =========================================================
# TASKS
# =========================================================

with tabs[3]:

    if not st.session_state.tasks:

        st.info(
            "No tasks."
        )

    for task in st.session_state.tasks:

        with st.expander(
            task["name"]
        ):

            st.write(
                f"Estimated: "
                f"{format_minutes(task['estimated_minutes'])}"
            )

            st.write(
                f"Complete by: "
                f"{task['deadline'].strftime('%B %d, %Y')}"
            )

            if task.get(
                "notes"
            ):

                st.write(
                    task[
                        "notes"
                    ]
                )

            if task.get(
                "url"
            ):

                st.markdown(
                    f"[Open link ↗]"
                    f"({task['url']})"
                )

            if st.button(
                "Delete",
                key=(
                    f"delete_task_"
                    f"{task['id']}"
                ),
            ):

                task_id = (
                    task["id"]
                )

                st.session_state.tasks = [
                    item
                    for item
                    in st.session_state.tasks
                    if (
                        item["id"]
                        != task_id
                    )
                ]

                rebuild_schedule()

                st.rerun()


# =========================================================
# EVENTS
# =========================================================

with tabs[4]:

    if not st.session_state.events:

        st.info(
            "No events."
        )

    for event in st.session_state.events:

        with st.expander(
            event["name"]
        ):

            if event["recurring"]:

                st.write(
                    "Repeats: "
                    + ", ".join(
                        event["days"]
                    )
                )

            else:

                st.write(
                    event["date"].strftime(
                        "%B %d, %Y"
                    )
                )

            st.write(
                f"{event['start_time'].strftime('%I:%M %p')} "
                f"– "
                f"{event['end_time'].strftime('%I:%M %p')}"
            )

            if event.get(
                "location"
            ):

                st.write(
                    f"Location: "
                    f"{event['location']}"
                )

            st.write(
                f"Buffer: "
                f"{event.get('buffer_before', 0)}m before "
                f"/ "
                f"{event.get('buffer_after', 0)}m after"
            )

            if event.get(
                "notes"
            ):

                st.write(
                    event[
                        "notes"
                    ]
                )

            if event.get(
                "url"
            ):

                st.markdown(
                    f"[Open event link ↗]"
                    f"({event['url']})"
                )

            if st.button(
                "Delete",
                key=(
                    f"delete_event_"
                    f"{event['id']}"
                ),
            ):

                event_id = (
                    event["id"]
                )

                st.session_state.events = [
                    item
                    for item
                    in st.session_state.events
                    if (
                        item["id"]
                        != event_id
                    )
                ]

                rebuild_schedule()

                st.rerun()


# =========================================================
# REMINDERS
# =========================================================

with tabs[5]:

    if not st.session_state.reminders:

        st.info(
            "No reminders."
        )

    for reminder in st.session_state.reminders:

        with st.expander(
            reminder["name"]
        ):

            st.write(
                f"{reminder['date'].strftime('%B %d, %Y')} "
                f"at "
                f"{reminder['time'].strftime('%I:%M %p')}"
            )

            if reminder[
                "reserve_minutes"
            ]:

                st.write(
                    f"Reserved: "
                    f"{format_minutes(reminder['reserve_minutes'])}"
                )

            if reminder.get(
                "notes"
            ):

                st.write(
                    reminder[
                        "notes"
                    ]
                )

            if reminder.get(
                "url"
            ):

                st.markdown(
                    f"[Open link ↗]"
                    f"({reminder['url']})"
                )

            if st.button(
                "Delete",
                key=(
                    f"delete_reminder_"
                    f"{reminder['id']}"
                ),
            ):

                reminder_id = (
                    reminder["id"]
                )

                st.session_state.reminders = [
                    item
                    for item
                    in st.session_state.reminders
                    if (
                        item["id"]
                        != reminder_id
                    )
                ]

                rebuild_schedule()

                st.rerun()


# =========================================================
# WORK HOURS
# =========================================================

with tabs[6]:

    if not st.session_state.work_windows:

        st.info(
            "No work windows."
        )

    for window in st.session_state.work_windows:

        with st.expander(
            ", ".join(
                window["days"]
            )
        ):

            st.write(
                f"{window['start_time'].strftime('%I:%M %p')} "
                f"– "
                f"{window['end_time'].strftime('%I:%M %p')}"
            )

            if st.button(
                "Delete Window",
                key=(
                    f"delete_window_"
                    f"{window['id']}"
                ),
            ):

                window_id = (
                    window["id"]
                )

                st.session_state.work_windows = [
                    item
                    for item
                    in st.session_state.work_windows
                    if (
                        item["id"]
                        != window_id
                    )
                ]

                rebuild_schedule()

                st.rerun()
