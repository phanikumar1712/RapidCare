from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client
from dotenv import load_dotenv
import os
import io
import math
from datetime import datetime, timezone
from PIL import Image
from triage import predict_severity
from classify_injury import classify_injury
import openrouteservice

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

load_dotenv(
    os.path.join(BASE_DIR, ".env")
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


class MissingSupabaseConfig(RuntimeError):
    """Raised when the DB is used but SUPABASE_URL / SUPABASE_KEY are unset."""


class _LazySupabase:
    """
    Create the Supabase client on first use rather than at import time.

    This lets the model-only endpoints (/classify-injury and the triage model)
    run without Supabase credentials configured, while endpoints that actually
    touch the database still fail with a clear message when .env is missing.
    """

    def __init__(self):
        self._client = None

    def __getattr__(self, name):
        if self._client is None:
            if not SUPABASE_URL or not SUPABASE_KEY:
                raise MissingSupabaseConfig(
                    "Missing SUPABASE_URL and/or SUPABASE_KEY. "
                    "Copy .env.example to .env and fill in the required values."
                )
            self._client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return getattr(self._client, name)


supabase = _LazySupabase()

app = FastAPI(title="RapidCare API")


@app.exception_handler(MissingSupabaseConfig)
async def missing_supabase_config_handler(request, exc):
    """Return an actionable message when the DB is used without credentials."""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SOSRequest(BaseModel):
    user_id: str
    latitude: float
    longitude: float
    emergency_type: str
    symptoms: str | None = None


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate straight-line distance between two GPS coordinates.
    Returns distance in kilometers.
    """

    R = 6371

    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)

    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


@app.post("/sos")
def create_sos(request: SOSRequest):

    # Predict severity from symptoms
    severity = None
    severity_confidence = None

    if request.symptoms:
        prediction = predict_severity(request.symptoms)

        severity_class = prediction["severity_class"]
        severity_confidence = prediction["confidence"]

        severity_mapping = {
            1: "High",
            2: "Medium-High",
            3: "Medium",
            4: "Low-Medium",
            5: "Low"
        }

        severity = severity_mapping.get(
            severity_class,
            "Unknown"
        )

    case_data = {
        "user_id": request.user_id,
        "latitude": request.latitude,
        "longitude": request.longitude,
        "emergency_type": request.emergency_type,
        "symptoms": request.symptoms,
        "severity": severity,
        "status": "active"
    }

    response = (
        supabase
        .table("cases")
        .insert(case_data)
        .execute()
    )

    return {
        "message": "SOS created successfully",
        "severity": severity,
        # The triage model's confidence — the UI shows this on the severity
        # card. Previously dropped here, which made the frontend display a
        # misleading "0% model confidence" for every real classification.
        "severity_confidence": severity_confidence,
        "case": response.data
    }
@app.post("/dispatch/{case_id}")
def dispatch_responder(case_id: str):

    # 1. Get the emergency case
    case_response = (
        supabase
        .table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    # If a responder is already assigned, don't assign another one
    if case.get("responder_id"):
        return {
            "message": "Responder already assigned",
            "case_id": case_id,
            "responder_id": case["responder_id"]
        }

    patient_lat = case["latitude"]
    patient_lon = case["longitude"]

    # 2. Get available responders
    responders_response = (
        supabase
        .table("responders")
        .select("*")
        .eq("availability_status", "available")
        .execute()
    )

    responders = responders_response.data

    if not responders:
        return {
            "message": "No available responders found",
            "case_id": case_id,
            "responder_assigned": False
        }

    # 3. OpenRouteService client
    api_key = os.getenv("OPENROUTESERVICE_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OpenRouteService API key not loaded"
        )

    ors_client = openrouteservice.Client(key=api_key)

    # 4. Find the responder with the shortest ETA
    best_responder = None
    best_distance = None
    best_eta = None

    for responder in responders:

        responder_lat = responder["latitude"]
        responder_lon = responder["longitude"]

        try:
            # ORS uses longitude, latitude
            route = ors_client.directions(
                coordinates=[
                    (responder_lon, responder_lat),
                    (patient_lon, patient_lat)
                ],
                profile="driving-car",
                format="geojson"
            )

            summary = route["features"][0]["properties"]["summary"]

            road_distance_km = round(
                summary["distance"] / 1000,
                2
            )

            eta_minutes = round(
                summary["duration"] / 60,
                1
            )

        except Exception:

            # Fallback to straight-line distance
            road_distance_km = round(
                calculate_distance(
                    patient_lat,
                    patient_lon,
                    responder_lat,
                    responder_lon
                ),
                2
            )

            eta_minutes = None

        # Choose the responder with the shortest ETA
        # If ETA is unavailable, use distance
        if best_responder is None:
            best_responder = responder
            best_distance = road_distance_km
            best_eta = eta_minutes

        elif eta_minutes is not None and (
            best_eta is None or eta_minutes < best_eta
        ):
            best_responder = responder
            best_distance = road_distance_km
            best_eta = eta_minutes

        elif eta_minutes is None and best_eta is None:
            if road_distance_km < best_distance:
                best_responder = responder
                best_distance = road_distance_km
                best_eta = eta_minutes

    # Safety check
    if best_responder is None:
        return {
            "message": "Unable to assign responder",
            "case_id": case_id,
            "responder_assigned": False
        }

    responder_id = best_responder["id"]

    # 5. Automatically assign responder to the case
    case_update = (
        supabase
        .table("cases")
        .update({
            "responder_id": responder_id,
            "status": "assigned"
        })
        .eq("id", case_id)
        .execute()
    )

    # 6. Mark responder as busy
    supabase \
        .table("responders") \
        .update({
            "availability_status": "busy"
        }) \
        .eq("id", responder_id) \
        .execute()

    # 7. Create an automatically accepted dispatch request
    dispatch_response = (
        supabase
        .table("dispatch_requests")
        .insert({
            "case_id": case_id,
            "responder_id": responder_id,
            "status": "accepted",
            "distance_km": best_distance,
            "eta_minutes": best_eta,
            "responded_at": datetime.now(timezone.utc).isoformat()
        })
        .execute()
    )

    return {
        "message": "Responder automatically assigned",
        "case_id": case_id,
        "responder_assigned": True,
        "responder": {
            "id": responder_id,
            "name": best_responder.get("name"),
            "phone": best_responder.get("phone"),
            "distance_km": best_distance,
            "eta_minutes": best_eta,
            "status": "accepted"
        },
        "dispatch_request": (
            dispatch_response.data[0]
            if dispatch_response.data
            else None
        )
    }
@app.post("/dispatch-request/{request_id}/accept")
def accept_dispatch_request(request_id: str):

    # 1. Get the dispatch request
    request_response = (
        supabase
        .table("dispatch_requests")
        .select("*")
        .eq("id", request_id)
        .execute()
    )

    if not request_response.data:
        raise HTTPException(
            status_code=404,
            detail="Dispatch request not found"
        )

    dispatch_request = request_response.data[0]

    # 2. Check if request is still pending
    if dispatch_request["status"] != "pending":
        raise HTTPException(
            status_code=400,
            detail="Dispatch request is no longer pending"
        )

    case_id = dispatch_request["case_id"]
    responder_id = dispatch_request["responder_id"]

    # 3. Check whether another responder already accepted
    case_response = (
        supabase
        .table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    if case["responder_id"] is not None:
        raise HTTPException(
            status_code=409,
            detail="Another responder has already accepted this case"
        )

    # 4. Assign responder to the case
    supabase.table("cases").update({
        "responder_id": responder_id
    }).eq("id", case_id).execute()

    # 5. Mark responder as busy
    supabase.table("responders").update({
        "availability_status": "busy"
    }).eq("id", responder_id).execute()

    # 6. Mark this request as accepted
    supabase.table("dispatch_requests").update({
        "status": "accepted",
        "responded_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", request_id).execute()

    # 7. Cancel all other pending requests for this case
    supabase.table("dispatch_requests").update({
        "status": "cancelled"
    }).eq("case_id", case_id).eq(
        "status", "pending"
    ).neq("id", request_id).execute()

    return {
        "message": "Responder accepted the emergency",
        "case_id": case_id,
        "responder_id": responder_id,
        "status": "accepted"
    }
@app.post("/hospital/{case_id}")
def find_nearest_hospital(case_id: str):

    # 1. Get emergency case
    case_response = (
        supabase
        .table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    patient_lat = case["latitude"]
    patient_lon = case["longitude"]

    # 2. Find hospitals with emergency service
    hospitals_response = (
        supabase
        .table("hospitals")
        .select("*")
        .eq("emergency_available", True)
        .execute()
    )

    hospitals = hospitals_response.data

    if not hospitals:
        return {
            "message": "No emergency hospitals available",
            "case_id": case_id
        }

    # 3. Calculate distance to each hospital
    hospital_distances = []

    for hospital in hospitals:

        distance = calculate_distance(
            patient_lat,
            patient_lon,
            hospital["latitude"],
            hospital["longitude"]
        )

        hospital_distances.append({
            "hospital": hospital,
            "distance_km": round(distance, 2)
        })

    # 4. Select nearest hospital
    nearest = min(
        hospital_distances,
        key=lambda x: x["distance_km"]
    )

    selected_hospital = nearest["hospital"]
    distance = nearest["distance_km"]

    # 5. Save hospital in the emergency case
    supabase.table("cases").update({
        "hospital_id": selected_hospital["id"]
    }).eq("id", case_id).execute()

    return {
        "message": "Nearest hospital selected successfully",
        "case_id": case_id,
        "hospital": selected_hospital,
        "distance_km": distance
    }
@app.get("/hospital-prebrief/{case_id}")
def hospital_prebrief(case_id: str):

    case_response = (
        supabase.table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(status_code=404, detail="Emergency case not found")

    case = case_response.data[0]

    # Get responder
    responder = None
    eta_minutes = None

    if case.get("responder_id"):

        responder_response = (
            supabase.table("responders")
            .select("*")
            .eq("id", case["responder_id"])
            .execute()
        )

        if responder_response.data:
            responder = responder_response.data[0]

        # Get accepted dispatch request and ETA
        dispatch_response = (
            supabase.table("dispatch_requests")
            .select("eta_minutes, distance_km")
            .eq("case_id", case_id)
            .eq("responder_id", case["responder_id"])
            .eq("status", "accepted")
            .execute()
        )

        if dispatch_response.data:
            eta_minutes = dispatch_response.data[0]["eta_minutes"]

    # Get hospital
    hospital = None

    if case.get("hospital_id"):

        hospital_response = (
            supabase.table("hospitals")
            .select("*")
            .eq("id", case["hospital_id"])
            .execute()
        )

        if hospital_response.data:
            hospital = hospital_response.data[0]

    return {
        "message": "Hospital pre-brief generated successfully",

        "case": {
            "case_id": case["id"],
            "emergency_type": case["emergency_type"],
            "symptoms": case["symptoms"],
            "severity": case["severity"],
            "patient_location": {
                "latitude": case["latitude"],
                "longitude": case["longitude"]
            }
        },

        "responder": responder,

        "transport": {
            "eta_minutes": eta_minutes
        },

        "hospital": hospital
    }


@app.get("/")
def home():
    return {
        "message": "RapidCare Backend is running!"
    }


@app.get("/test-db")
def test_database():

    response = (
        supabase
        .table("users")
        .select("*")
        .limit(5)
        .execute()
    )

    return {
        "message": "Supabase connection successful",
        "users": response.data
    }
@app.get("/route-test")
def route_test():
    api_key = os.getenv("OPENROUTESERVICE_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="OpenRouteService API key not loaded"
    )

    ors_client = openrouteservice.Client(
    key=api_key
)

    # Example coordinates
    # [longitude, latitude]
    patient = (83.3956, 18.1066)
    responder = (83.41, 18.12)

    try:
        
        
        route = ors_client.directions(
            coordinates=[
                responder,
                patient
            ],
            profile="driving-car",
            format="geojson"
        )

        summary = route["features"][0]["properties"]["summary"]

        distance_km = round(
            summary["distance"] / 1000,
            2
        )

        duration_minutes = round(
            summary["duration"] / 60,
            1
        )

        return {
            "message": "Route calculated successfully",
            "distance_km": distance_km,
            "eta_minutes": duration_minutes
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
@app.post("/case/{case_id}/en-route")
def responder_en_route(case_id: str):

    case_response = (
        supabase
        .table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    if not case.get("responder_id"):
        raise HTTPException(
            status_code=400,
            detail="No responder has accepted this case"
        )

    # A responder may be assigned either by the automatic dispatcher
    # (status "assigned") or by manually accepting a dispatch request on a
    # case that is still "active". Both are valid starting points.
    if case["status"] not in {"active", "assigned"}:
        raise HTTPException(
            status_code=400,
            detail=f"Case is already {case['status']}"
        )

    supabase.table("cases").update({
        "status": "en_route",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", case_id).execute()

    return {
        "message": "Responder is now en route",
        "case_id": case_id,
        "responder_id": case["responder_id"],
        "status": "en_route"
    }
@app.post("/case/{case_id}/status")
def update_case_status(case_id: str, status: str):

    allowed_statuses = {
        "arrived",
        "completed",
        "cancelled"
    }

    if status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Use: {', '.join(allowed_statuses)}"
        )

    case_response = (
        supabase.table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    supabase.table("cases").update({
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", case_id).execute()

    # Make responder available again after case completion/cancellation
    if status in ["completed", "cancelled"] and case.get("responder_id"):
        supabase.table("responders").update({
            "availability_status": "available"
        }).eq("id", case["responder_id"]).execute()

    return {
        "message": f"Case status updated to {status}",
        "case_id": case_id,
        "status": status
    }
@app.get("/analytics")
def get_analytics():

    cases_response = (
        supabase
        .table("cases")
        .select("id, severity, status, created_at")
        .execute()
    )

    cases = cases_response.data

    total_cases = len(cases)

    severity_counts = {
        "High": 0,
        "Medium-High": 0,
        "Medium": 0,
        "Low-Medium": 0,
        "Low": 0
    }

    status_counts = {}

    for case in cases:

        severity = case.get("severity")
        status = case.get("status")

        if severity in severity_counts:
            severity_counts[severity] += 1

        if status:
            status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "message": "Analytics generated successfully",
        "total_cases": total_cases,
        "severity_distribution": severity_counts,
        "status_distribution": status_counts
    }

@app.get("/emergency-fallback/{case_id}")
def emergency_fallback(case_id: str):

    case_response = (
        supabase.table("cases")
        .select("*")
        .eq("id", case_id)
        .execute()
    )

    if not case_response.data:
        raise HTTPException(
            status_code=404,
            detail="Emergency case not found"
        )

    case = case_response.data[0]

    # Get available responders
    responders_response = (
        supabase.table("responders")
        .select("name, phone, latitude, longitude, responder_type")
        .eq("availability_status", "available")
        .execute()
    )

    responders = responders_response.data

    return {
        "message": "Emergency fallback information generated",
        "case_id": case_id,
        "emergency_type": case["emergency_type"],
        "severity": case["severity"],
        "patient_location": {
            "latitude": case["latitude"],
            "longitude": case["longitude"]
        },
        "emergency_contacts": responders
    }


def _is_image(image_bytes: bytes) -> bool:
    """True if the bytes actually decode as an image Pillow understands."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as probe:
            probe.verify()
        return True
    except Exception:
        return False


@app.post("/classify-injury")
async def classify_injury_endpoint(file: UploadFile = File(...)):
    """
    Accept an image file, run the wound/injury classifier, and return
    the predicted injury type with confidence score and per-class probabilities.
    """
    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Validate the bytes themselves rather than the declared content type:
    # several multipart clients (e.g. Dart's http MultipartFile.fromPath) send
    # "application/octet-stream" for real photos, so the header is unreliable.
    if not _is_image(image_bytes):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image")

    try:
        result = classify_injury(image_bytes)
        return {
            "message": "Classification successful",
            **result,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Classification failed: {exc}")