import streamlit as st
from datetime import date, datetime, time, timedelta
import math


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Smart Study Planner",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Smart Study Planner")
st.caption(
    "A workload-aware planner for courses, studying, projects, "
    "assignments, events, tasks, and reminders."
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
}


for key, default_value in DEFAULTS.items():
    if key not in st.session_state:
        if isinstance(default_value, list):
            st.session_state[key] = []
        else:
            st.session_state[key] = default_value

if "show_preferences" not in st.session_state:
    st.session_state.show_preferences = True 


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

def get_week_start(day):
    return day - timedelta(days=day.weekday())


def get_visible_week():
    monday = (
        get_week_start(date.today())
        + timedelta(weeks=st.session_state.week_offset)
    )

    return [
        monday + timedelta(days=i)
        for i in range(7)
    ]


def format_minutes(minutes):
    minutes = int(round(minutes))

    hours = minutes // 60
    mins = minutes % 60

    if hours and mins:
        return f"{hours}h {mins}m"

    if hours:
        return f"{hours}h"

    return f"{mins}m"


def combine(day, clock_time):
    return datetime.combine(day, clock_time)


def minutes_between(start, end):
    return int((end - start).total_seconds() / 60)


def course_by_name(name):
    for course in st.session_state.courses:
        if course["name"] == name:
            return course

    return None


def course_color(name):
    course = course_by_name(name)

    if course:
        return course["color"]

    return "#777777"


def priority_number(priority):
    return PRIORITY_VALUE.get(priority, 2)


def deadline_urgency(deadline):
    days_left = (deadline - date.today()).days

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
        deadline_urgency(item["deadline"])
        + priority_number(item.get("priority", "Normal")) * 10
    )

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

    recommended_minutes = (
        base_times[difficulty]
        * familiarity_multiplier[familiarity]
        * goal_multiplier[goal]
    )

    return round(recommended_minutes)
# =========================================================
# COURSE IDS / WORK IDS
# =========================================================

def next_id(collection):
    if not collection:
        return 1

    return max(item["id"] for item in collection) + 1


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

    merged = [intervals[0]]

    for current_start, current_end in intervals[1:]:
        previous_start, previous_end = merged[-1]

        if current_start <= previous_end:
            merged[-1] = (
                previous_start,
                max(previous_end, current_end),
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
    weekday = day.strftime("%A")

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

    return merge_intervals(intervals)


# =========================================================
# FIXED EVENTS
# =========================================================

def events_for_date(day):
    weekday = day.strftime("%A")

    results = []

    for event in st.session_state.events:
        include = False

        if event["recurring"]:
            include = weekday in event["days"]

        elif event["date"] == day:
            include = True

        if not include:
            continue

        results.append(
            {
                "name": event["name"],
                "start": combine(
                    day,
                    event["start_time"],
                ),
                "end": combine(
                    day,
                    event["end_time"],
                ),
                "type": "Event",
            }
        )

    return sorted(
        results,
        key=lambda item: item["start"],
    )


# =========================================================
# REMINDER RESERVATIONS
# =========================================================

def reserved_reminders_for_date(day):
    results = []

    for reminder in st.session_state.reminders:
        if reminder["date"] != day:
            continue

        if reminder["reserve_minutes"] <= 0:
            continue

        start = combine(
            day,
            reminder["time"],
        )

        end = (
            start
            + timedelta(
                minutes=reminder["reserve_minutes"]
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

def intervals_overlap(start1, end1, start2, end2):
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
    free = work_windows_for_date(day)

    for event in events_for_date(day):
        free = subtract_interval(
            free,
            event["start"],
            event["end"],
        )

    for start, end in reserved_reminders_for_date(day):
        free = subtract_interval(
            free,
            start,
            end,
        )

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
# DAILY WORKLOAD
# =========================================================

def academic_minutes_on_day(day):
    return sum(
        block["work_minutes"]
        for block in st.session_state.schedule
        if (
            block["date"] == day
            and block["type"] in {
                "Study",
                "Assignment",
                "Project",
            }
        )
    )


def course_minutes_on_day(day, course):
    return sum(
        block["work_minutes"]
        for block in st.session_state.schedule
        if (
            block["date"] == day
            and block.get("course") == course
            and block["type"] in {
                "Study",
                "Assignment",
                "Project",
            }
        )
    )


def academic_capacity_left(day):
    return max(
        0,
        st.session_state.daily_academic_cap
        - academic_minutes_on_day(day),
    )


def course_capacity_left(day, course):
    if not st.session_state.use_course_cap:
        return 100000

    return max(
        0,
        st.session_state.daily_course_cap
        - course_minutes_on_day(day, course),
    )


# =========================================================
# BREAK CALCULATIONS
# =========================================================

def elapsed_time_needed(work_minutes):
    """
    Returns total clock time required for a work block,
    including configured breaks.
    """

    work_minutes = int(work_minutes)

    if not st.session_state.include_breaks:
        return work_minutes

    focus_length = st.session_state.break_after_minutes
    break_length = st.session_state.break_length_minutes

    if work_minutes <= focus_length:
        return work_minutes

    full_focus_chunks = work_minutes // focus_length

    if work_minutes % focus_length == 0:
        breaks = max(
            0,
            full_focus_chunks - 1,
        )
    else:
        breaks = full_focus_chunks

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
    """
    Converts a session into work blocks + optional break blocks.
    """

    current = start
    remaining = work_minutes

    focus_length = (
        st.session_state.break_after_minutes
        if st.session_state.include_breaks
        else work_minutes
    )

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
                "course": item.get("course", ""),
                "type": item["type"],
                "date": day,
                "start": current,
                "end": focus_end,
                "work_minutes": focus_minutes,
                "deadline": item["deadline"],
                "source_id": item.get("source_id"),
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
                    minutes=st.session_state.break_length_minutes
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
                    "deadline": item["deadline"],
                    "source_id": None,
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
    daily_left = academic_capacity_left(day)

    if course:
        course_left = course_capacity_left(
            day,
            course,
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

    free = free_intervals_for_date(day)

    for start, end in free:
        interval_minutes = minutes_between(
            start,
            end,
        )

        possible_work = allowed_work

        while possible_work >= 10:
            clock_needed = elapsed_time_needed(
                possible_work
            )

            if clock_needed <= interval_minutes:
                return (
                    start,
                    possible_work,
                )

            possible_work -= 5

    return None


# =========================================================
# DISTRIBUTED STUDY SCHEDULER
# =========================================================

def schedule_study_topics():
    remaining = {}

    for topic in st.session_state.study_topics:
        remaining[topic["id"]] = topic["recommended_minutes"]

    if not remaining:
        return

    current_day = date.today()

    latest_deadline = max(
        topic["deadline"]
        for topic in st.session_state.study_topics
    )

    while current_day <= latest_deadline:

        # Eligible topics for this specific day
        eligible = [
            topic
            for topic in st.session_state.study_topics
            if (
                remaining[topic["id"]] > 0
                and current_day <= topic["deadline"]
            )
        ]

        if not eligible:
            current_day += timedelta(days=1)
            continue

        # Urgent first, but rotate courses naturally.
        eligible.sort(
            key=lambda topic: (
                -item_score(topic),
                course_minutes_on_day(
                    current_day,
                    topic["course"],
                ),
                remaining[topic["id"]],
            )
        )

        made_progress = True

        while eligible and made_progress:
            made_progress = False

            # Round-robin through current eligible topics
            for topic in eligible:
                topic_id = topic["id"]

                if remaining[topic_id] <= 0:
                    continue

                remaining_days = max(
                    1,
                    (
                        topic["deadline"]
                        - current_day
                    ).days
                    + 1,
                )

                # Spread work across remaining days.
                fair_share = math.ceil(
                    remaining[topic_id]
                    / remaining_days
                )

                desired = max(
                    30,
                    fair_share,
                )

                desired = min(
                    desired,
                    st.session_state.preferred_study_minutes,
                    topic["max_session_minutes"],
                    remaining[topic_id],
                )

                slot = find_slot(
                    current_day,
                    desired,
                    topic["course"],
                )

                if slot is None:
                    continue

                start, actual_minutes = slot

                item = {
                    "name": topic["topic"],
                    "course": topic["course"],
                    "type": "Study",
                    "deadline": topic["deadline"],
                    "source_id": topic_id,
                }

                create_work_and_break_blocks(
                    item,
                    current_day,
                    start,
                    actual_minutes,
                )

                remaining[topic_id] -= (
                    actual_minutes
                )

                made_progress = True

        current_day += timedelta(days=1)


# =========================================================
# LINKED STUDY DATE
# =========================================================

def project_study_start_date(work_item):
    linked_topic_ids = work_item.get(
        "linked_topic_ids",
        [],
    )

    if not linked_topic_ids:
        return date.today()

    study_blocks = [
        block
        for block in st.session_state.schedule
        if (
            block["type"] == "Study"
            and block["source_id"] in linked_topic_ids
        )
    ]

    if not study_blocks:
        return date.today()

    latest_block = max(
        study_blocks,
        key=lambda block: block["end"],
    )

    return latest_block["date"]


# =========================================================
# ASSIGNMENT / PROJECT SCHEDULER
# =========================================================

def schedule_academic_work():
    items = list(
        st.session_state.academic_work
    )

    items.sort(
        key=lambda item: (
            -item_score(item),
            item["estimated_minutes"],
        )
    )

    # Course rotation tracker
    last_course = None

    while True:
        unfinished = [
            item
            for item in items
            if item["remaining_minutes"] > 0
        ]

        if not unfinished:
            break

        # Penalize immediately repeating same course
        unfinished.sort(
            key=lambda item: (
                item["course"] == last_course,
                -item_score(item),
                item["remaining_minutes"],
            )
        )

        progress = False

        for item in unfinished:
            start_day = date.today()

            if item["type"] == "Project":
                start_day = max(
                    start_day,
                    project_study_start_date(item),
                )

            deadline = item["deadline"]

            if not item["allow_deadline_day"]:
                deadline -= timedelta(days=1)

            current_day = start_day

            while current_day <= deadline:
                desired = min(
                    item["remaining_minutes"],
                    item["max_block_minutes"],
                )

                slot = find_slot(
                    current_day,
                    desired,
                    item["course"],
                )

                if slot is not None:
                    start, actual_minutes = slot

                    schedule_item = {
                        "name": item["name"],
                        "course": item["course"],
                        "type": item["type"],
                        "deadline": item["deadline"],
                        "source_id": item["id"],
                    }

                    create_work_and_break_blocks(
                        schedule_item,
                        current_day,
                        start,
                        actual_minutes,
                    )

                    item["remaining_minutes"] -= (
                        actual_minutes
                    )

                    last_course = item["course"]
                    progress = True
                    break

                current_day += timedelta(days=1)

            if progress:
                break

        if not progress:
            break


# =========================================================
# GENERIC TASK SCHEDULER
# =========================================================

def schedule_tasks():
    items = []

    for task in st.session_state.tasks:
        item = task.copy()
        item["remaining_minutes"] = task["estimated_minutes"]
        items.append(item)

    # Urgency first, then shortest task.
    items.sort(
        key=lambda item: (
            -item_score(item),
            item["remaining_minutes"],
        )
    )

    for item in items:
        day = date.today()

        while (
            day <= item["deadline"]
            and item["remaining_minutes"] > 0
        ):
            desired = min(
                item["remaining_minutes"],
                item["max_block_minutes"],
            )

            # Generic tasks do not count toward
            # academic limits.
            free = free_intervals_for_date(day)

            scheduled = False

            for start, end in free:
                available = minutes_between(
                    start,
                    end,
                )

                if available < 10:
                    continue

                block_minutes = min(
                    desired,
                    available,
                )

                block_end = (
                    start
                    + timedelta(
                        minutes=block_minutes
                    )
                )

                st.session_state.schedule.append(
                    {
                        "name": item["name"],
                        "course": "",
                        "type": "Task",
                        "date": day,
                        "start": start,
                        "end": block_end,
                        "work_minutes": block_minutes,
                        "deadline": item["deadline"],
                        "source_id": item["id"],
                    }
                )

                item["remaining_minutes"] -= (
                    block_minutes
                )

                scheduled = True
                break

            if not scheduled:
                day += timedelta(days=1)


# =========================================================
# REBUILD SCHEDULE
# =========================================================

def rebuild_schedule():
    st.session_state.schedule = []

    # Fresh remaining-minute values for academic work
    for item in st.session_state.academic_work:
        item["remaining_minutes"] = (
            item["estimated_minutes"]
        )

    schedule_study_topics()
    schedule_academic_work()
    schedule_tasks()


# =========================================================
# PRETTIER CALENDAR CARDS
# =========================================================

def hex_to_rgba(hex_color, alpha=0.12):
    hex_color = hex_color.lstrip("#")

    if len(hex_color) != 6:
        return f"rgba(120,120,120,{alpha})"

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    return f"rgba({r},{g},{b},{alpha})"


def render_card(
    title,
    subtitle,
    start,
    end,
    item_type,
    color="#777777",
):
    background = hex_to_rgba(
        color,
        0.10,
    )

    html = f"""
    <div style="
        border-left: 5px solid {color};
        background: {background};
        padding: 10px 12px;
        margin: 8px 0;
        border-radius: 9px;
    ">
        <div style="
            font-weight: 700;
            font-size: 0.98rem;
        ">
            {title}
        </div>

        <div style="
            opacity: 0.76;
            font-size: 0.82rem;
            margin-top: 2px;
        ">
            {subtitle}
        </div>

        <div style="
            margin-top: 6px;
            font-size: 0.87rem;
        ">
            {start.strftime("%I:%M %p")} –
            {end.strftime("%I:%M %p")}
        </div>

        <div style="
            opacity: 0.65;
            font-size: 0.76rem;
            margin-top: 3px;
        ">
            {item_type}
        </div>
    </div>
    """

    st.markdown(
        html,
        unsafe_allow_html=True,
    )


# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:

    st.header("Planner Setup")

    # =====================================================
    # 1. COURSES
    # =====================================================

    st.subheader("1. Courses")

    new_course_name = st.text_input(
        "Course name",
        placeholder="Biology",
        key="new_course_name",
    )

    new_course_color = st.color_picker(
        "Course color",
        "#4F8EF7",
        key="new_course_color",
    )

    if st.button(
        "Add Course",
        use_container_width=True,
        key="add_course_button",
    ):
        cleaned_name = new_course_name.strip()

        existing_names = [
            course["name"].lower()
            for course in st.session_state.courses
        ]

        if not cleaned_name:
            st.error(
                "Enter a course name."
            )

        elif cleaned_name.lower() in existing_names:
            st.error(
                "That course already exists."
            )

        else:
            st.session_state.courses.append(
                {
                    "id": next_id(
                        st.session_state.courses
                    ),
                    "name": cleaned_name,
                    "color": new_course_color,
                }
            )

            st.rerun()

    if st.session_state.courses:
        for course in st.session_state.courses:
            st.markdown(
                f"""
                <div style="
                    display:flex;
                    align-items:center;
                    gap:8px;
                    margin:5px 0;
                ">
                    <div style="
                        width:14px;
                        height:14px;
                        border-radius:4px;
                        background:{course["color"]};
                    "></div>
                    <span>{course["name"]}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )

    else:
        st.info(
            "Add at least one course for academic planning."
        )

    st.divider()

    # =====================================================
    # 2. WORK HOURS
    # =====================================================

    st.subheader("2. Work Hours")

    st.caption(
        "Flexible work will only be placed inside these windows."
    )

    if "work_days_picker" not in st.session_state:
        st.session_state.work_days_picker = []

    shortcut1, shortcut2, shortcut3 = st.columns(3)

    with shortcut1:
        if st.button(
            "Weekdays",
            key="weekdays_shortcut",
            use_container_width=True,
        ):
            st.session_state.work_days_picker = WEEKDAYS.copy()

    with shortcut2:
        if st.button(
            "Every Day",
            key="everyday_shortcut",
            use_container_width=True,
        ):
            st.session_state.work_days_picker = DAYS.copy()

    with shortcut3:
        if st.button(
            "Clear",
            key="clear_days_shortcut",
            use_container_width=True,
        ):
            st.session_state.work_days_picker = []

    selected_work_days = st.multiselect(
        "Work days",
        DAYS,
        key="work_days_picker",
    )

    work_start = st.time_input(
        "Start",
        value=time(17, 0),
        key="work_window_start",
    )

    work_end = st.time_input(
        "End",
        value=time(21, 0),
        key="work_window_end",
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
                    "days": selected_work_days.copy(),
                    "start_time": work_start,
                    "end_time": work_end,
                }
            )

            rebuild_schedule()
            st.rerun()

    if not st.session_state.work_windows:
        st.warning(
            "Create at least one work window before "
            "adding flexible academic work."
        )

    st.divider()

# =====================================================
# 3. PLANNER PREFERENCES
# =====================================================

st.subheader("3. Planner Preferences")

if not st.session_state.show_preferences:

    if st.button(
        "Edit Planner Preferences",
        use_container_width=True,
        key="edit_preferences_button",
    ):
        st.session_state.show_preferences = True
        st.rerun()

else:

    include_breaks = st.checkbox(
        "Include breaks during long work sessions",
        value=st.session_state.include_breaks,
        key="pref_include_breaks",
        help=(
            "Adds scheduled breaks during longer study "
            "or academic work sessions."
        ),
    )

    if include_breaks:

        break_after = st.number_input(
            "Work before taking a break (minutes)",
            min_value=30,
            max_value=180,
            value=st.session_state.break_after_minutes,
            step=15,
            key="pref_break_after",
        )

        break_length = st.number_input(
            "Break length (minutes)",
            min_value=5,
            max_value=60,
            value=st.session_state.break_length_minutes,
            step=5,
            key="pref_break_length",
        )

    else:

        break_after = st.session_state.break_after_minutes
        break_length = st.session_state.break_length_minutes


    preferred_study = st.number_input(
        "Typical study block (minutes)",
        min_value=30,
        max_value=180,
        value=st.session_state.preferred_study_minutes,
        step=15,
        key="pref_study_session",
    )


    max_study = st.number_input(
        "Longest study block (minutes)",
        min_value=30,
        max_value=240,
        value=st.session_state.max_study_minutes,
        step=15,
        key="pref_max_study",
    )


    daily_academic_cap = st.number_input(
        "Daily schoolwork limit (minutes)",
        min_value=60,
        max_value=720,
        value=st.session_state.daily_academic_cap,
        step=30,
        key="pref_daily_academic_cap",
    )


    use_course_cap = st.checkbox(
        "Limit how much time one course can use per day",
        value=st.session_state.use_course_cap,
        key="pref_use_course_cap",
    )


    if use_course_cap:

        course_cap = st.number_input(
            "Daily limit for one course (minutes)",
            min_value=30,
            max_value=480,
            value=st.session_state.daily_course_cap,
            step=30,
            key="pref_course_cap",
        )

    else:

        course_cap = st.session_state.daily_course_cap


    if st.button(
        "Save Preferences",
        use_container_width=True,
        key="save_preferences",
    ):

        if preferred_study > max_study:

            st.error(
                "Typical study block cannot be longer "
                "than the longest study block."
            )

        else:

            st.session_state.include_breaks = include_breaks
            st.session_state.break_after_minutes = int(break_after)
            st.session_state.break_length_minutes = int(break_length)

            st.session_state.preferred_study_minutes = int(
                preferred_study
            )

            st.session_state.max_study_minutes = int(
                max_study
            )

            st.session_state.daily_academic_cap = int(
                daily_academic_cap
            )

            st.session_state.use_course_cap = use_course_cap

            st.session_state.daily_course_cap = int(
                course_cap
            )

            st.session_state.show_preferences = False

            rebuild_schedule()

            st.rerun()

    # =====================================================
    # 4. ADD ITEMS
    # =====================================================

    st.subheader("4. Add to Planner")

    item_type = st.radio(
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

    course_names = [
        course["name"]
        for course in st.session_state.courses
    ]

    can_schedule_academic = (
        bool(st.session_state.courses)
        and bool(st.session_state.work_windows)
    )

    # =====================================================
    # STUDY TOPIC
    # =====================================================

    if item_type == "Study Topic":

        if not can_schedule_academic:
            st.info(
                "Create at least one course and one work "
                "window first."
            )

        else:
            topic_name = st.text_input(
                "Topic",
                placeholder="Object-Oriented Programming",
                key="topic_name",
            )

            topic_course = st.selectbox(
                "Course",
                course_names,
                key="topic_course",
            )

            # Existing projects in same course
            available_projects = [
                item
                for item in st.session_state.academic_work
                if (
                    item["course"] == topic_course
                    and item["type"] == "Project"
                )
            ]

            project_options = {
                "None": None
            }

            for project in available_projects:
                project_options[
                    project["name"]
                ] = project["id"]

            linked_project_name = st.selectbox(
                "Related project",
                list(project_options.keys()),
                key="topic_linked_project",
                help=(
                    "Optional. If selected, the planner "
                    "schedules this studying before project work."
                ),
            )

            linked_project_id = project_options[
                linked_project_name
            ]

            linked_project = None

            if linked_project_id is not None:
                linked_project = next(
                    item
                    for item in available_projects
                    if item["id"] == linked_project_id
                )

                default_topic_deadline = (
                    linked_project["deadline"]
                )

            else:
                default_topic_deadline = (
                    date.today()
                    + timedelta(days=7)
                )

            topic_deadline = st.date_input(
                "Learn by",
                value=default_topic_deadline,
                key="topic_deadline",
            )

            familiarity = st.selectbox(
                "Familiarity",
                [
                    "Never seen it",
                    "Some exposure",
                    "Comfortable",
                    "Review only",
                ],
                key="topic_familiarity",
            )

            difficulty = st.selectbox(
                "Difficulty",
                [
                    "Easy",
                    "Medium",
                    "Hard",
                ],
                key="topic_difficulty",
            )

            goal = st.selectbox(
                "Goal",
                [
                    "Understand the basics",
                    "Complete practice problems",
                    "Use it in a project",
                    "Prepare for a test",
                ],
                key="topic_goal",
            )

            topic_priority = st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="topic_priority",
            )

            topic_max_session = st.number_input(
                "Maximum session for this topic",
                min_value=30,
                max_value=240,
                value=st.session_state.max_study_minutes,
                step=15,
                key="topic_max_session",
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
                if not topic_name.strip():
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
                            "topic": topic_name.strip(),
                            "name": topic_name.strip(),
                            "course": topic_course,
                            "deadline": topic_deadline,
                            "recommended_minutes": recommended_minutes,
                            "priority": topic_priority,
                            "max_session_minutes": int(
                                topic_max_session
                            ),
                            "linked_project_id": linked_project_id,
                            "familiarity": familiarity,
                            "difficulty": difficulty,
                            "goal": goal,
                        }
                    )

                    # Add dependency to project
                    if linked_project_id is not None:
                        for project in st.session_state.academic_work:
                            if project["id"] == linked_project_id:
                                if (
                                    topic_id
                                    not in project["linked_topic_ids"]
                                ):
                                    project["linked_topic_ids"].append(
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

        if not can_schedule_academic:
            st.info(
                "Create at least one course and one work "
                "window first."
            )

        else:
            work_name = st.text_input(
                item_type,
                placeholder=(
                    "Research Paper"
                    if item_type == "Assignment"
                    else "Python Project 4"
                ),
                key="academic_work_name",
            )

            work_course = st.selectbox(
                "Course",
                course_names,
                key="academic_work_course",
            )

            work_due = st.date_input(
                "Due date",
                value=date.today()
                + timedelta(days=7),
                key="academic_work_due",
            )

            hours = st.number_input(
                "Estimated hours",
                min_value=0,
                max_value=100,
                value=2,
                key="academic_work_hours",
            )

            mins = st.number_input(
                "Additional minutes",
                min_value=0,
                max_value=59,
                value=0,
                key="academic_work_minutes",
            )

            work_priority = st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="academic_work_priority",
            )

            max_block = st.number_input(
                "Maximum single work block",
                min_value=30,
                max_value=480,
                value=180,
                step=30,
                key="academic_work_max_block",
            )

            allow_due_day = st.checkbox(
                "Allow work on due date",
                value=True,
                key="academic_work_allow_due",
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

                if not work_name.strip():
                    st.error(
                        f"Enter a {item_type.lower()} name."
                    )

                elif total <= 0:
                    st.error(
                        "Estimated completion time must be "
                        "greater than zero."
                    )

                else:
                    st.session_state.academic_work.append(
                        {
                            "id": next_id(
                                st.session_state.academic_work
                            ),
                            "name": work_name.strip(),
                            "course": work_course,
                            "type": item_type,
                            "deadline": work_due,
                            "estimated_minutes": int(total),
                            "remaining_minutes": int(total),
                            "priority": work_priority,
                            "max_block_minutes": int(
                                max_block
                            ),
                            "allow_deadline_day": allow_due_day,
                            "linked_topic_ids": [],
                        }
                    )

                    rebuild_schedule()
                    st.rerun()

    # =====================================================
    # EVENT
    # =====================================================

    elif item_type == "Event":

        event_name = st.text_input(
            "Event",
            placeholder="Gym",
            key="event_name",
        )

        recurring = st.checkbox(
            "Repeats weekly",
            key="event_recurring",
        )

        if recurring:
            event_days = st.multiselect(
                "Days",
                DAYS,
                key="event_days",
            )

            event_date = None

        else:
            event_date = st.date_input(
                "Date",
                key="event_date",
            )

            event_days = []

        start_time = st.time_input(
            "Start time",
            value=time(17, 0),
            key="event_start",
        )

        end_time = st.time_input(
            "End time",
            value=time(18, 0),
            key="event_end",
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
                    "End time must be after start time."
                )

            elif recurring and not event_days:
                st.error(
                    "Select at least one day."
                )

            else:
                st.session_state.events.append(
                    {
                        "id": next_id(
                            st.session_state.events
                        ),
                        "name": event_name.strip(),
                        "recurring": recurring,
                        "days": event_days,
                        "date": event_date,
                        "start_time": start_time,
                        "end_time": end_time,
                    }
                )

                rebuild_schedule()
                st.rerun()

    # =====================================================
    # TASK
    # =====================================================

    elif item_type == "Task":

        if not st.session_state.work_windows:
            st.info(
                "Create a work window first."
            )

        else:
            task_name = st.text_input(
                "Task",
                placeholder="Grocery shopping",
                key="task_name",
            )

            task_deadline = st.date_input(
                "Complete by",
                value=date.today()
                + timedelta(days=3),
                key="task_deadline",
            )

            task_hours = st.number_input(
                "Hours",
                min_value=0,
                max_value=24,
                value=1,
                key="task_hours",
            )

            task_minutes = st.number_input(
                "Additional minutes",
                min_value=0,
                max_value=59,
                value=0,
                key="task_minutes",
            )

            task_priority = st.selectbox(
                "Priority",
                [
                    "Low",
                    "Normal",
                    "High",
                ],
                index=1,
                key="task_priority",
            )

            task_max_block = st.number_input(
                "Maximum block",
                min_value=10,
                max_value=480,
                value=120,
                step=10,
                key="task_max_block",
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

                if not task_name.strip():
                    st.error(
                        "Enter a task."
                    )

                elif total <= 0:
                    st.error(
                        "Estimated time must be greater than zero."
                    )

                else:
                    st.session_state.tasks.append(
                        {
                            "id": next_id(
                                st.session_state.tasks
                            ),
                            "name": task_name.strip(),
                            "deadline": task_deadline,
                            "estimated_minutes": int(total),
                            "priority": task_priority,
                            "max_block_minutes": int(
                                task_max_block
                            ),
                        }
                    )

                    rebuild_schedule()
                    st.rerun()

    # =====================================================
    # REMINDER
    # =====================================================

    elif item_type == "Reminder":

        reminder_name = st.text_input(
            "Reminder",
            placeholder="Switch laundry",
            key="reminder_name",
        )

        reminder_date = st.date_input(
            "Date",
            key="reminder_date",
        )

        reminder_time = st.time_input(
            "Time",
            value=time(18, 0),
            key="reminder_time",
        )

        reserve_time = st.checkbox(
            "Reserve time",
            key="reminder_reserve",
        )

        reserve_minutes = 0

        if reserve_time:
            reserve_minutes = st.number_input(
                "Minutes",
                min_value=5,
                max_value=120,
                value=10,
                step=5,
                key="reminder_minutes",
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
                        "name": reminder_name.strip(),
                        "date": reminder_date,
                        "time": reminder_time,
                        "reserve_minutes": int(
                            reserve_minutes
                        ),
                    }
                )

                rebuild_schedule()
                st.rerun()


# =========================================================
# WEEK CONTROLS
# =========================================================

left, center, right = st.columns(
    [1, 3, 1]
)

with left:
    if st.button(
        "← Previous Week",
        key="previous_week",
    ):
        st.session_state.week_offset -= 1
        st.rerun()

with center:
    week_dates = get_visible_week()

    st.subheader(
        f"{week_dates[0].strftime('%b %d')} – "
        f"{week_dates[-1].strftime('%b %d, %Y')}"
    )

with right:
    if st.button(
        "Next Week →",
        key="next_week",
    ):
        st.session_state.week_offset += 1
        st.rerun()


regen_col, today_col = st.columns(2)

with regen_col:
    if st.button(
        "🔄 Regenerate Schedule",
        use_container_width=True,
        key="regen_schedule",
    ):
        rebuild_schedule()
        st.rerun()

with today_col:
    if st.button(
        "Today",
        use_container_width=True,
        key="return_today",
    ):
        st.session_state.week_offset = 0
        st.rerun()


st.divider()


# =========================================================
# WEEKLY WORKLOAD SUMMARY
# =========================================================

week_dates = get_visible_week()

scheduled_academic = sum(
    block["work_minutes"]
    for block in st.session_state.schedule
    if (
        block["date"] in week_dates
        and block["type"]
        in {"Study", "Assignment", "Project"}
    )
)

available_minutes = sum(
    minutes_between(start, end)
    for day in week_dates
    for start, end in work_windows_for_date(day)
)

summary1, summary2, summary3 = st.columns(3)

summary1.metric(
    "Academic work scheduled",
    format_minutes(scheduled_academic),
)

summary2.metric(
    "Work-window time",
    format_minutes(available_minutes),
)

summary3.metric(
    "Courses",
    len(st.session_state.courses),
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
        day.strftime("%B %d")
    )

    for start, end in work_windows_for_date(day):
        st.caption(
            f"🕒 Work window "
            f"{start.strftime('%I:%M %p')} – "
            f"{end.strftime('%I:%M %p')}"
        )

    calendar_items = []

    for event in events_for_date(day):
        calendar_items.append(
            {
                "name": event["name"],
                "course": "",
                "type": "Event",
                "start": event["start"],
                "end": event["end"],
            }
        )

    for block in st.session_state.schedule:
        if block["date"] == day:
            calendar_items.append(block)

    calendar_items.sort(
        key=lambda item: item["start"]
    )

    for item in calendar_items:

        item_type = item["type"]

        if item_type == "Break":
            st.caption(
                f"☕ {item['start'].strftime('%I:%M %p')} – "
                f"{item['end'].strftime('%I:%M %p')} Break"
            )
            continue

        if item_type == "Study":
            icon = "📚"

        elif item_type == "Assignment":
            icon = "📝"

        elif item_type == "Project":
            icon = "🛠️"

        elif item_type == "Task":
            icon = "✅"

        else:
            icon = "📅"

        course = item.get(
            "course",
            "",
        )

        color = (
            course_color(course)
            if course
            else "#777777"
        )

        subtitle = course

        if not subtitle:
            subtitle = item_type

        render_card(
            title=f"{icon} {item['name']}",
            subtitle=subtitle,
            start=item["start"],
            end=item["end"],
            item_type=item_type,
            color=color,
        )

    reminders = [
        reminder
        for reminder in st.session_state.reminders
        if reminder["date"] == day
    ]

    reminders.sort(
        key=lambda item: item["time"]
    )

    for reminder in reminders:
        st.markdown(
            f"🔔 **{reminder['time'].strftime('%I:%M %p')} "
            f"— {reminder['name']}**"
        )

    # Deadlines
    for work in st.session_state.academic_work:
        if work["deadline"] == day:
            color = course_color(
                work["course"]
            )

            st.markdown(
                f"""
                <div style="
                    border-left:4px solid {color};
                    padding-left:8px;
                    margin-top:8px;
                ">
                    <b>🚨 Due: {work["name"]}</b><br>
                    <span style="opacity:.7">
                        {work["course"]}
                    </span>
                </div>
                """,
                unsafe_allow_html=True,
            )


row1 = st.columns(4)

for index in range(4):
    with row1[index]:
        render_day(
            week_dates[index]
        )


st.write("")


row2 = st.columns(3)

for index in range(3):
    with row2[index]:
        render_day(
            week_dates[index + 4]
        )


# =========================================================
# OVERLOAD / SCHEDULE CHECK
# =========================================================

st.divider()

st.header("Schedule Check")


warnings = []


def scheduled_minutes(
    source_id,
    item_type,
):
    return sum(
        block["work_minutes"]
        for block in st.session_state.schedule
        if (
            block.get("source_id") == source_id
            and block["type"] == item_type
        )
    )


for topic in st.session_state.study_topics:

    actual = scheduled_minutes(
        topic["id"],
        "Study",
    )

    missing = (
        topic["recommended_minutes"]
        - actual
    )

    if missing > 0:
        warnings.append(
            f"{topic['course']} — {topic['topic']} "
            f"needs {format_minutes(missing)} more study time "
            f"before {topic['deadline'].strftime('%b %d')}."
        )


for work in st.session_state.academic_work:

    actual = scheduled_minutes(
        work["id"],
        work["type"],
    )

    missing = (
        work["estimated_minutes"]
        - actual
    )

    if missing > 0:
        warnings.append(
            f"{work['course']} — {work['name']} "
            f"needs {format_minutes(missing)} more work time "
            f"before {work['deadline'].strftime('%b %d')}."
        )


for task in st.session_state.tasks:

    actual = scheduled_minutes(
        task["id"],
        "Task",
    )

    missing = (
        task["estimated_minutes"]
        - actual
    )

    if missing > 0:
        warnings.append(
            f"{task['name']} needs "
            f"{format_minutes(missing)} more time before "
            f"{task['deadline'].strftime('%b %d')}."
        )


if warnings:

    st.warning(
        "⚠️ The current workload does not completely fit "
        "inside the available schedule."
    )

    for warning in warnings:
        st.write(
            f"• {warning}"
        )

else:

    if (
        st.session_state.study_topics
        or st.session_state.academic_work
        or st.session_state.tasks
    ):
        st.success(
            "Everything currently fits into your schedule."
        )

    else:
        st.info(
            "Add some coursework or tasks to build the schedule."
        )


# =========================================================
# MANAGE PLANNER
# =========================================================

st.divider()

st.header("Manage Planner")


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

        col1, col2 = st.columns(
            [4, 1]
        )

        with col1:
            new_color = st.color_picker(
                course["name"],
                course["color"],
                key=f"edit_course_color_{course['id']}",
            )

            if new_color != course["color"]:
                course["color"] = new_color

        with col2:
            if st.button(
                "Delete",
                key=f"delete_course_{course['id']}",
            ):
                course_name = course["name"]

                course_used = any(
                    topic["course"] == course_name
                    for topic in st.session_state.study_topics
                ) or any(
                    item["course"] == course_name
                    for item in st.session_state.academic_work
                )

                if course_used:
                    st.error(
                        "Delete that course's study topics and "
                        "assignments/projects first."
                    )

                else:
                    st.session_state.courses.pop(
                        index
                    )

                    st.rerun()


# =========================================================
# STUDY TOPICS
# =========================================================

with tabs[1]:

    if not st.session_state.study_topics:
        st.info(
            "No study topics."
        )

    for topic in st.session_state.study_topics:

        with st.expander(
            f"{topic['course']} — {topic['topic']}"
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
                f"Priority: {topic['priority']}"
            )

            if topic["linked_project_id"]:
                linked = next(
                    (
                        item
                        for item in st.session_state.academic_work
                        if item["id"]
                        == topic["linked_project_id"]
                    ),
                    None,
                )

                if linked:
                    st.write(
                        f"Supports project: "
                        f"{linked['name']}"
                    )

            if st.button(
                "Delete Topic",
                key=f"delete_topic_{topic['id']}",
            ):
                topic_id = topic["id"]

                st.session_state.study_topics = [
                    item
                    for item in st.session_state.study_topics
                    if item["id"] != topic_id
                ]

                for work in st.session_state.academic_work:
                    if topic_id in work["linked_topic_ids"]:
                        work["linked_topic_ids"].remove(
                            topic_id
                        )

                rebuild_schedule()
                st.rerun()


# =========================================================
# ASSIGNMENTS / PROJECTS
# =========================================================

with tabs[2]:

    if not st.session_state.academic_work:
        st.info(
            "No assignments or projects."
        )

    for item in st.session_state.academic_work:

        with st.expander(
            f"{item['course']} — {item['name']}"
        ):
            st.write(
                f"Type: {item['type']}"
            )

            st.write(
                f"Estimated work: "
                f"{format_minutes(item['estimated_minutes'])}"
            )

            st.write(
                f"Due: "
                f"{item['deadline'].strftime('%B %d, %Y')}"
            )

            st.write(
                f"Priority: {item['priority']}"
            )

            if item["linked_topic_ids"]:
                names = []

                for topic_id in item["linked_topic_ids"]:
                    topic = next(
                        (
                            topic
                            for topic in st.session_state.study_topics
                            if topic["id"] == topic_id
                        ),
                        None,
                    )

                    if topic:
                        names.append(
                            topic["topic"]
                        )

                if names:
                    st.write(
                        "Prerequisite study: "
                        + ", ".join(names)
                    )

            if st.button(
                "Delete",
                key=f"delete_work_{item['id']}",
            ):
                item_id = item["id"]

                st.session_state.academic_work = [
                    work
                    for work in st.session_state.academic_work
                    if work["id"] != item_id
                ]

                for topic in st.session_state.study_topics:
                    if topic["linked_project_id"] == item_id:
                        topic["linked_project_id"] = None

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

            if st.button(
                "Delete",
                key=f"delete_task_{task['id']}",
            ):
                task_id = task["id"]

                st.session_state.tasks = [
                    item
                    for item in st.session_state.tasks
                    if item["id"] != task_id
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
                    + ", ".join(event["days"])
                )
            else:
                st.write(
                    event["date"].strftime(
                        "%B %d, %Y"
                    )
                )

            st.write(
                f"{event['start_time'].strftime('%I:%M %p')} – "
                f"{event['end_time'].strftime('%I:%M %p')}"
            )

            if st.button(
                "Delete",
                key=f"delete_event_{event['id']}",
            ):
                event_id = event["id"]

                st.session_state.events = [
                    item
                    for item in st.session_state.events
                    if item["id"] != event_id
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
                f"at {reminder['time'].strftime('%I:%M %p')}"
            )

            if reminder["reserve_minutes"]:
                st.write(
                    f"Reserved time: "
                    f"{format_minutes(reminder['reserve_minutes'])}"
                )

            if st.button(
                "Delete",
                key=f"delete_reminder_{reminder['id']}",
            ):
                reminder_id = reminder["id"]

                st.session_state.reminders = [
                    item
                    for item in st.session_state.reminders
                    if item["id"] != reminder_id
                ]

                rebuild_schedule()
                st.rerun()


# =========================================================
# WORK WINDOWS
# =========================================================

with tabs[6]:

    if not st.session_state.work_windows:
        st.info(
            "No work windows."
        )

    for window in st.session_state.work_windows:

        with st.expander(
            ", ".join(window["days"])
        ):
            st.write(
                f"{window['start_time'].strftime('%I:%M %p')} – "
                f"{window['end_time'].strftime('%I:%M %p')}"
            )

            if st.button(
                "Delete Window",
                key=f"delete_window_{window['id']}",
            ):
                window_id = window["id"]

                st.session_state.work_windows = [
                    item
                    for item in st.session_state.work_windows
                    if item["id"] != window_id
                ]

                rebuild_schedule()
                st.rerun()