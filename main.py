# main.py: all endpoints stored here

# imports + setup
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from contextlib import asynccontextmanager
import asyncio # handles background tasks - allow simultaneous tasks
from datetime import datetime, timezone, timedelta # calculating 24 hours windows
import os
from dotenv import load_dotenv

# imports 7 functions from db.py (database)
from db import (
    connect_db, # connects to mongodb
    insert_reading, # saves temp to database when arduino send data
    get_readings_24h, # gets all readings from last 24 hrs - used in background tasks to calculate variability
    get_all_patients, # gets all patients - called in background task and dashboard endpoint
    store_score, # saves variability score - background task
    create_alert, # creates alert - when score is high
    ack_alert # marks alert as acknolwedge by nurse
)

# imports some more functions
from arduino_handler import connect_arduino, read_temperature, close_arduino
# MIGHT want to delete detect outliers and use ai model
from calculations import calculate_variability, detect_outliers

# runs function - loads .env file into memory so os.getenv() can work w it
load_dotenv()

# setup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # connects to mongodb and arduino
    connect_db()
    connect_arduino()

    # infinite loop that runs every 6 hours
    # calculates patient score every 6 hours
    async def background_calc():
        while True:
            # pauses for 6 hours
            await asyncio.sleep(6 * 3600)
            # below begins after 6 hours
            patients = get_all_patients() # store patients from database into a list
            
            # files through the list of patients
            for patient in patients:
                # gets last 24 h temp readings for each patient
                # 24h b/c although we calculating score every 6 hours, we need enough data for variability from the last 24 hours
                readings = get_readings_24h(patient["_id"])
                
                # only calculate if more than 10 readings in the past 24 hours
                if len(readings) > 10:
                    # extracts only temperature from readings into a list
                    temps = [r["temperature"] for r in readings]

                    # TENTATIVE - removes outliers from temperature list
                    filtered, outliers = detect_outliers(temps)
                    # second derivative calculation for delirium risk score
                    score = calculate_variability(filtered)
                    # save score - every 6 hours each patient gets a new score
                    store_score(patient["_id"], score)

                    # trigger alert if score too high
                    if score >= 8.0:
                        create_alert(patient["_id"], "red", score)
                    elif score >= 5.0:
                        create_alert(patient["_id"], "yellow", score)
    
    # starts the background task while app handles requests
    asyncio.create_task(background_calc())

    yield

    # shutdown
    close_arduino()

app = FastAPI(lifespan=lifespan)


# --- endpoints ---

# home page - shows webpage running
@app.get("/")
async def home():
    return {"message: " "Hospital Delirium Alert System running"}

# endpoint that streams live temperature data from arduino
@app.get("/stream")
async def stream_data():
    # never stops streaming data until browser closes
    async def generate():
        while True:
            temp = await asyncio.to_thread(read_temperature)
            if temp:
                try:
                    insert_reading("patient1", float(temp))
                    yield f"data: {temp}\n\n"
                except:
                    pass
            await asyncio.sleep(60) # read temperature every minute
    return StreamingResponse(generate(), media_type="text/event-stream")

# dashboard endpoint that returns all patients organized into the alert tiers
# returns a dictoinary with patients organized in the 3 tiers
# returned to the browser as JSON
@app.get("/api/dashboard")
async def dashboard():
    patients = get_all_patients()
    # organize patients by alter tier
    result = {"red": [], "yellow": [], "green:": []}

    for patient in patients:
        from db import get_latest_score
        score_doc = get_latest_score(patient["_id"])
        score = score_doc["score"] if score_doc else 0

        if score >= 8.0:
            tier = "red"
        elif score >= 5.0:
            tier = "yellow"
        else:
            tier = "green"
        
        days = (datetime.now(timezone.utc) - patient["admission_date"])

        result[tier].append({
            "id": str(patient["_id"]),
            "name": patient["name"],
            "room": patient["room_number"],
            "score": round(score, 2),
            "days_admitted": days
        })
    return result

# get one patient's full profile
# returns a patients name room days admitted
# returns a graph for variability over time over a week
# returns alert history (moving between alert tiers) over a week
@app.get("/api/patient/{patient_id}")
async def patient_detail(patient_id: str):
    from db import get_patient, get_scores_7_days, get_alerts_7_days

    patient = get_patient(patient_id)
    if not patient:
        return {"error:" "Patient not found"}
    
    scores = get_scores_7_days(patient_id)
    alerts = get_alerts_7_days(patient_id)

    return {
        "patient": {
            "name": patient["name"],
            "room": patient["room_number"],
            "baseline_temp": patient["baseline_temp"],
            "days_admitted": (datetime.now(timezone.utc) - patient["admission_date"]).days
        },
        "scores": [{"time": str(s["calculated_at"]), "score": s["score"]} for s in scores],
        "alerts": [{"type": a["alert_type"], "time": str(a["triggered_at"])} for a in alerts]
    }

# collects acknowledge status from browser and posts to server
@app.post("/api/alert/{alert_id}/acknowledge")
async def ack_alert(alert_id: str):
    ack_alert(alert_id)
    return {"status": "acknowledged"}