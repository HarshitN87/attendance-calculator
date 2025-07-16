import streamlit as st
st.set_page_config(page_title="Attendance Tracker", layout="wide")
import pandas as pd
import json
import os
from datetime import datetime

# File paths
timetable_file = 'timetable.csv'
calendar_file = 'academic_calendar.csv'
data_file = 'attendance_data.csv'

# --- Streamlit Cloud file upload support ---
# If timetable or calendar CSVs are missing, prompt user to upload them
missing_files = []
for f in [timetable_file, calendar_file]:
    if not os.path.exists(f):
        missing_files.append(f)
if missing_files:
    st.error(f"Missing required file(s): {', '.join(missing_files)}. Please upload them below.")
    for f in missing_files:
        uploaded = st.file_uploader(f"Upload {f}", type=["csv"], key=f)
        if uploaded:
            with open(f, "wb") as out:
                out.write(uploaded.read())
            st.success(f"Uploaded {f}. Please reload the app.")
    st.stop()

# Initialize attendance_data.csv if not present
def initialize_attendance_csv(subjects):
    if not os.path.exists(data_file):
        df = pd.DataFrame([
            {'subject': s, 'present': 0, 'absent': 0} for s in subjects
        ])
        df.to_csv(data_file, index=False)

# Load timetable
timetable = pd.read_csv(timetable_file)
subjects = set()
for day in timetable.columns[1:]:
    for subj in timetable[day]:
        s = str(subj).strip()
        if s and s.lower() != 'break':
            subjects.add(s)
subjects = sorted(subjects)

initialize_attendance_csv(subjects)

# Load academic calendar
dates_df = pd.read_csv(calendar_file)
# Only keep teaching days (not breaks)
dates_df = dates_df[dates_df['Activity'].isnull()]

# Count number of each weekday in the semester
weekday_counts = dates_df['Day'].value_counts().to_dict()

# Build subject schedule: {subject: [days of week]} (with lab merging)
subject_days = {s: set() for s in subjects}
subject_lab_sessions = {s: set() for s in subjects}  # (day, start_col) for labs
for i, row in timetable.iterrows():
    day = row['Day']
    prev_subj = None
    for col_idx, subj in enumerate(timetable.columns[1:], 1):
        s = str(row[subj]).strip()
        if s and s.lower() != 'break':
            # Check if this is a lab and if it's a continuation
            if 'lab' in s.lower():
                if prev_subj == s:
                    # Already counted this lab session
                    continue
                # Mark this lab session by (day, col_idx)
                subject_lab_sessions[s].add((day, col_idx))
            else:
                subject_days[s].add(day)
            prev_subj = s
        else:
            prev_subj = None

# Calculate total scheduled classes per subject (labs as merged sessions)
subject_total_classes = {}
for s in subjects:
    if 'lab' in s.lower():
        # Count unique lab sessions
        total = 0
        for (day, col_idx) in subject_lab_sessions[s]:
            # Only count if the day is a teaching day
            if day in weekday_counts:
                total += weekday_counts[day]
        subject_total_classes[s] = total
    else:
        total = 0
        for day in subject_days[s]:
            total += weekday_counts.get(day, 0)
        # Double the amount of classes for TCS-502
        if s.replace(' ', '').upper().startswith('TCS-502'):
            total *= 2
        subject_total_classes[s] = total

def load_attendance():
    if os.path.exists(data_file):
        df = pd.read_csv(data_file)
        return {row['subject']: {'present': int(row['present']), 'absent': int(row['absent'])} for _, row in df.iterrows()}
    else:
        # Initialize attendance data
        return {s: {'present': 0, 'absent': 0} for s in subjects}

def save_attendance(data):
    df = pd.DataFrame([
        {'subject': s, 'present': data[s]['present'], 'absent': data[s]['absent']} for s in subjects
    ])
    df.to_csv(data_file, index=False)

def attendance_percentage(present, absent, total):
    attended = present
    total_classes = min(present + absent, total)
    if total_classes == 0:
        return 0.0
    return (attended / total_classes) * 100

def classes_can_miss(present, absent, total):
    # How many more can you miss and still be >= 75%?
    attended = present
    missed = absent
    remaining = total - (present + absent)
    can_miss = 0
    for i in range(remaining + 1):
        perc = (attended / (attended + missed + i)) * 100 if (attended + missed + i) > 0 else 100
        if perc >= 75:
            can_miss = i
        else:
            break
    return can_miss

def classes_needed_to_reach_75(present, absent, total):
    attended = present
    missed = absent
    remaining = total - (present + absent)
    need = 0
    while (attended + need) <= total:
        perc = ((attended + need) / (attended + missed + need)) * 100 if (attended + missed + need) > 0 else 0
        if perc >= 75:
            return need
        need += 1
    return None

# --- Multipage UI ---
page = st.sidebar.selectbox("Select Page", ["Dashboard", "Calendar View"])

if page == "Dashboard":
    st.title("Attendance Tracker")
    attendance_data = load_attendance()
    cols = st.columns(3)
    for idx, subject in enumerate(subjects):
        with cols[idx % 3]:
            st.subheader(subject)
            total = subject_total_classes[subject]
            present = attendance_data[subject]['present']
            absent = attendance_data[subject]['absent']
            percent = attendance_percentage(present, absent, total)
            color = 'green' if percent >= 75 else 'orange' if percent >= 50 else 'red'
            st.progress(percent / 100, text=f"{percent:.2f}%")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Present", key=f"present_{subject}"):
                    if present + absent < total:
                        attendance_data[subject]['present'] += 1
                        save_attendance(attendance_data)
                        st.rerun()
            with c2:
                if st.button("Absent", key=f"absent_{subject}"):
                    if present + absent < total:
                        attendance_data[subject]['absent'] += 1
                        save_attendance(attendance_data)
                        st.rerun()
            st.write(f"Attended: {present} / {total}")
            # Show how many more classes to attend for 75%
            remaining = total - (present + absent)
            need = 0
            if percent < 75:
                while (present + need) <= total:
                    perc = ((present + need) / (present + absent + need)) * 100 if (present + absent + need) > 0 else 0
                    if perc >= 75:
                        break
                    need += 1
                if (present + need) > total:
                    st.info("Not possible to reach 75% with remaining classes.")
                else:
                    st.info(f"Attend next {need} class(es) to reach 75%.")
            else:
                # If already above 75%, show how many more classes must be attended to stay above 75% (i.e., if you miss all but these)
                min_needed = max(0, int((0.75 * (present + absent + remaining) - present + 0.9999)))
                st.info(f"You must attend at least {min_needed} of the remaining {remaining} class(es) to stay above 75%.")
            if percent >= 75:
                can_miss = classes_can_miss(present, absent, total)
                st.success(f"You can miss {can_miss} more class(es) and stay above 75%.")
            else:
                need = classes_needed_to_reach_75(present, absent, total)
                if need is not None:
                    st.warning(f"Attend next {need} class(es) to reach 75%.")
                else:
                    st.error("Not possible to reach 75% with remaining classes.")
    # Overall attendance
    st.header("Overall Attendance")
    total_present = 0
    total_absent = 0
    total_classes = 0
    for s in subjects:
        present = attendance_data[s]['present']
        absent = attendance_data[s]['absent']
        total = subject_total_classes[s]
        if 'lab' in s.lower():
            total_present += present * 2
            total_absent += absent * 2
            total_classes += total * 2
        else:
            total_present += present
            total_absent += absent
            total_classes += total
    overall_percent = attendance_percentage(total_present, total_absent, total_classes)
    st.progress(overall_percent / 100, text=f"{overall_percent:.2f}%")
    st.write(f"Total Attended: {total_present} / {total_classes}")
    # Add: How many more classes to attend to reach 75% overall
    remaining = total_classes - (total_present + total_absent)
    need = 0
    if overall_percent < 75:
        while (total_present + need) <= total_classes:
            perc = ((total_present + need) / (total_present + total_absent + need)) * 100 if (total_present + total_absent + need) > 0 else 0
            if perc >= 75:
                break
            need += 1
        if (total_present + need) > total_classes:
            st.error("Not possible to reach 75% overall with remaining classes.")
        else:
            st.warning(f"Attend next {need} class(es) to reach 75% overall attendance.")
    if st.button("Reset All Attendance Data"):
        attendance_data = {s: {'present': 0, 'absent': 0} for s in subjects}
        save_attendance(attendance_data)
        st.rerun()

elif page == "Calendar View":
    st.title("Calendar View - Mark Attendance by Date")
    attendance_data = load_attendance()
    # Only allow picking teaching days
    valid_dates = pd.to_datetime(dates_df['Date']).dt.date.unique()
    selected_date = st.date_input("Select a date", min_value=min(valid_dates), max_value=max(valid_dates))
    if selected_date not in valid_dates:
        st.warning("Selected date is not a teaching day.")
        st.stop()
    # Find the weekday name for the selected date
    weekday = pd.to_datetime(str(selected_date)).day_name()
    # Find the timetable row for this weekday
    timetable_row = timetable[timetable['Day'] == weekday]
    if timetable_row.empty:
        st.info("No classes scheduled for this day.")
        st.stop()
    # Gather scheduled subjects for this day (with lab merging)
    scheduled_subjects = []
    prev_subj = None
    for col_idx, col in enumerate(timetable.columns[1:], 1):
        s = str(timetable_row.iloc[0][col]).strip()
        if s and s.lower() != 'break':
            if 'lab' in s.lower():
                if prev_subj == s:
                    continue
            scheduled_subjects.append(s)
            prev_subj = s
        else:
            prev_subj = None
    st.write(f"### Scheduled subjects on {selected_date} ({weekday}):")
    st.write(", ".join(scheduled_subjects))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Mark all as Attended", key=f"attend_{selected_date}"):
            for s in scheduled_subjects:
                if attendance_data[s]['present'] + attendance_data[s]['absent'] < subject_total_classes[s]:
                    attendance_data[s]['present'] += 1
            save_attendance(attendance_data)
            st.success("Marked all as attended for this day.")
            st.rerun()
    with c2:
        if st.button("Mark all as Absent", key=f"absent_{selected_date}"):
            for s in scheduled_subjects:
                if attendance_data[s]['present'] + attendance_data[s]['absent'] < subject_total_classes[s]:
                    attendance_data[s]['absent'] += 1
            save_attendance(attendance_data)
            st.success("Marked all as absent for this day.")
            st.rerun()
    st.info("You can use this page to quickly fill attendance for any teaching day. Attendance is updated for all scheduled subjects on the selected day.")
