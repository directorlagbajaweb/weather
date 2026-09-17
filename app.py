import streamlit as st

from weather_api import (
    get_advisory,
    get_air_quality,
    get_current_weather,
    get_forecast,
    search_cities,
)

st.set_page_config(page_title="Weather", page_icon="🌤️")


@st.cache_data(ttl=600)
def cached_search(city_name):
    return search_cities(city_name)


@st.cache_data(ttl=600)
def cached_current(lat, lon):
    return get_current_weather(lat, lon)


@st.cache_data(ttl=600)
def cached_forecast(lat, lon):
    return get_forecast(lat, lon)


@st.cache_data(ttl=600)
def cached_air(lat, lon):
    return get_air_quality(lat, lon)


AQI_COLOURS = {1: "green", 2: "green", 3: "orange", 4: "red", 5: "red"}

ACTIVITY_LABELS = {
    "Spraying": "spraying",
    "Outdoor event": "event",
    "Drying / storage": "drying",
}

VERDICT_COLOURS = {"go": "green", "caution": "orange", "no-go": "red"}

AQI_ADVICE = {
    1: "Air is clean. Fine for outdoor activity of any length.",
    2: "Air is acceptable. Fine for going outside, though anyone unusually "
    "sensitive may notice it on a long or strenuous outing.",
    3: "Moderate pollution. Most people are fine outdoors, but children, older "
    "people and anyone with asthma or a heart condition should keep hard "
    "exercise short.",
    4: "Poor air. Limit time outdoors and avoid strenuous activity. Sensitive "
    "groups should stay inside where possible and keep windows shut.",
    5: "Very poor air. Stay indoors if you can, keep windows shut, and avoid "
    "outdoor exercise entirely. Wear a proper mask if you must go out.",
}


def format_city(city):
    parts = [city["name"]]
    if city["state"]:
        parts.append(city["state"])
    parts.append(city["country"])
    return ", ".join(parts)


st.title("Weather")

city_name = st.text_input("City")

if city_name:
    try:
        matches = cached_search(city_name)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    if not matches:
        st.warning(f"No cities found for '{city_name}'.")
        st.stop()

    selected = st.selectbox("Select a city", matches, format_func=format_city)

    tab1, tab2, tab3 = st.tabs(["Weather", "Air quality", "Advisory"])

    with tab1:
        try:
            with st.spinner("Loading..."):
                weather = cached_current(selected["lat"], selected["lon"])
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

        st.header(format_city(selected))
        st.markdown(f"# {weather['temp']:.1f}°C")

        col1, col2, col3 = st.columns(3)
        col1.metric("Feels like", f"{weather['feels_like']:.1f}°C")
        col2.metric("Humidity", f"{weather['humidity']}%")
        col3.metric("Wind speed", f"{weather['wind_speed']} m/s")

        st.write(weather["description"].capitalize())

        try:
            with st.spinner("Loading..."):
                forecast = cached_forecast(selected["lat"], selected["lon"])
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

        st.subheader("5-day forecast")

        days = forecast[:5]
        for column, day in zip(st.columns(len(days)), days):
            column.write(f"**{day['date']:%a}** {day['date'].day}")
            column.image(
                f"https://openweathermap.org/img/wn/{day['icon']}@2x.png", width=80
            )
            column.write(f"{round(day['temp_max'])}° / {round(day['temp_min'])}°")

    with tab2:
        try:
            with st.spinner("Loading..."):
                air = cached_air(selected["lat"], selected["lon"])
        except RuntimeError as exc:
            st.error(str(exc))
            st.stop()

        colour = AQI_COLOURS.get(air["aqi"], "gray")
        st.markdown(
            f"<h1 style='color: {colour}'>{air['aqi_label']}</h1>",
            unsafe_allow_html=True,
        )

        col1, col2, col3 = st.columns(3)
        col1.metric("PM2.5", f"{air['pm2_5']} µg/m³")
        col2.metric("PM10", f"{air['pm10']} µg/m³")
        col3.metric("Ozone", f"{air['o3']} µg/m³")

        st.write(AQI_ADVICE.get(air["aqi"], "No air quality guidance available."))

        st.caption(
            "PM2.5 is the fine dust measure - it spikes during harmattan, when "
            "dust blown down from the Sahara can keep levels high for days."
        )

    with tab3:
        activity_label = st.radio("Activity", list(ACTIVITY_LABELS))
        advisory = get_advisory(days, ACTIVITY_LABELS[activity_label])

        for row in advisory:
            day_col, verdict_col, reason_col = st.columns([1, 1, 4])
            day_col.write(f"**{row['date']:%a}** {row['date'].day}")
            colour = VERDICT_COLOURS.get(row["verdict"], "gray")
            verdict_col.markdown(
                f"<span style='background-color: {colour}; color: white; "
                f"padding: 2px 10px; border-radius: 10px'>{row['verdict']}</span>",
                unsafe_allow_html=True,
            )
            reason_col.write(row["reason"])

        st.caption(
            "These thresholds are defaults, not local knowledge - someone who "
            "does the work should tune them for the crop, the sprayer and the site."
        )
