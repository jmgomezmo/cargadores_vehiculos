import os
import psycopg2
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
app = FastAPI(title="Cynergiax API - B2B2C")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def get_db():
    conn = psycopg2.connect(
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASS"), host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT")
    )
    with conn.cursor() as cur:
        cur.execute("SET search_path TO ocpp;")
    return conn

# Frontend Models (Se Mantiene nomenclatura en inglés para compatibilidad con lo existente)
class ReservationRequest(BaseModel):
    user_id: int
    charge_point_id: int
    start_time: str
    end_time: str

class StartChargeRequest(BaseModel):
    user_id: int
    charge_point_id: int

@app.post("/api/reservar")
def crear_reserva(req: ReservationRequest):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO reservas (id_usuario, id_cargador, fecha_inicio, fecha_fin, estado)
                    VALUES (%s, %s, %s, %s, 'Pendiente') RETURNING id_reserva;
                """, (req.user_id, req.charge_point_id, req.start_time, req.end_time))
                res_id = cur.fetchone()[0]
                conn.commit()
        return {"status": "success", "ticket_reserva": f"RES-{res_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/iniciar_carga")
def iniciar_carga(req: StartChargeRequest):
    try:
        payload_ocpp = {"charge_point_id": f"CP_AVANZADO_0{req.charge_point_id}", "id_tag": "TIME_TEST_TAG"}
        respuesta = requests.post("http://127.0.0.1:9090/remote_start", json=payload_ocpp)
        if respuesta.status_code == 200:
            return {"status": "success", "message": "Orden procesada"}
        
        err_msg = respuesta.json().get("error", "El hardware rechazó la orden")
        raise HTTPException(status_code=400, detail=err_msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/detener_carga")
def detener_carga(req: StartChargeRequest):
    try:
        payload_ocpp = {"charge_point_id": f"CP_AVANZADO_0{req.charge_point_id}"}
        respuesta = requests.post("http://127.0.0.1:9090/remote_stop", json=payload_ocpp)
        if respuesta.status_code == 200:
            return {"status": "success", "message": "Carga detenida"}
        
        err_msg = respuesta.json().get("error", "Error en hardware")
        raise HTTPException(status_code=400, detail=err_msg)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/usuario/{user_id}")
def get_usuario(user_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id_usuario, nombre, apellidos, id_tag FROM usuarios WHERE id_usuario = %s;", (user_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuario no encontrado")
                return {"id": row[0], "nombre": f"{row[1]} {row[2]}", "avatar": f"{row[1][0]}{row[2][0]}", "id_tag": row[3]}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/cargador/{cp_id}/estado")
def get_estado_cargador(cp_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ocpp_id, estado_actual FROM cargadores WHERE id_cargador = %s;", (cp_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Cargador no encontrado")
                return {"id": cp_id, "nombre": row[0], "estado": row[1]}
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sesion/activa/{user_id}")
def get_sesion_activa(user_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT t.id_sesion, t.fecha_inicio, t.medidor_inicio, 
                           COALESCE((SELECT MAX(CAST(valor AS NUMERIC)) FROM telemetria WHERE id_sesion = t.id_sesion), t.medidor_inicio) as current_meter
                    FROM sesiones_carga t 
                    WHERE t.id_usuario = %s AND t.fecha_fin IS NULL 
                    ORDER BY t.fecha_inicio DESC LIMIT 1;
                """, (user_id,))
                row = cur.fetchone()
                
                if not row:
                    return {"activa": False}
                
                trans_id, start_time, meter_start, current_meter = row
                minutos = int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)
                kwh_consumidos = (float(current_meter) - float(meter_start)) / 1000.0
                
                return {
                    "activa": True, "transaction_id": trans_id, "minutos": minutos,
                    "energia_kwh": round(kwh_consumidos, 2), "potencia_kw": 7.2
                }
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/usuario/{user_id}/historial")
def get_historial(user_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(id_sesion) as total_sesiones,
                        COALESCE(SUM(energia_kwh), 0) as total_kwh,
                        COALESCE(SUM(costo_energia), 0) as costo_total
                    FROM sesiones_carga 
                    WHERE id_usuario = %s AND fecha_fin IS NOT NULL;
                """, (user_id,))
                stats = cur.fetchone()
                return {
                    "total_sesiones": stats[0], "total_kwh": round(stats[1], 1), "costo_total_cop": round(stats[2], 0)
                }
    except Exception as e:
         raise HTTPException(status_code=500, detail=str(e))