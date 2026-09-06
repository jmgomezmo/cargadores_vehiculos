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
                # El estado inicial al agendar es 'Reservado'
                cur.execute("""
                    INSERT INTO reservas (id_usuario, id_cargador, fecha_inicio, fecha_fin, estado)
                    VALUES (%s, %s, %s, %s, 'Reservado') RETURNING id_reserva;
                """, (req.user_id, req.charge_point_id, req.start_time, req.end_time))
                res_id = cur.fetchone()[0]
                conn.commit()
        return {"status": "success", "ticket_reserva": f"RES-{res_id}"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/iniciar_carga")
def iniciar_carga(req: StartChargeRequest):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 1. Extracción del id_tag real
                cur.execute("SELECT id_tag FROM usuarios WHERE id_usuario = %s;", (req.user_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuario no encontrado")
                id_tag_usuario = row[0]

                # 2. Actualizar estado de reserva de 'Reservado' a 'Activa' si aplica
                cur.execute("""
                    UPDATE reservas 
                    SET estado = 'Activa' 
                    WHERE id_usuario = %s AND id_cargador = %s AND estado = 'Reservado'
                      AND CURRENT_TIMESTAMP BETWEEN fecha_inicio AND fecha_fin;
                """, (req.user_id, req.charge_point_id))
                conn.commit()

        payload_ocpp = {
            "charge_point_id": f"CP_AVANZADO_0{req.charge_point_id}",
            "id_tag": id_tag_usuario
        }
        
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
        
        # respuesta = requests.post("http://api.cynergiax.com:9090/remote_stop", json=payload_ocpp)
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

@app.get("/api/sesion/activa/{user_id}")
def get_sesion_activa(user_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 1. Obtener tarifa activa
                cur.execute("""
                    SELECT precio_por_kwh FROM tarifas 
                    WHERE valido_desde <= CURRENT_TIMESTAMP 
                      AND (valido_hasta IS NULL OR valido_hasta >= CURRENT_TIMESTAMP)
                    ORDER BY valido_desde DESC LIMIT 1;
                """)
                tarifa_row = cur.fetchone()
                precio_kwh = float(tarifa_row[0]) if tarifa_row else 1850.0

                # 2. Buscar sesión activa y su cargador asociado en la tabla cargadores
                cur.execute("""
                    SELECT t.id_sesion, t.fecha_inicio, t.medidor_inicio, c.ocpp_id,
                           COALESCE((SELECT MAX(CAST(valor AS NUMERIC)) FROM telemetria WHERE id_sesion = t.id_sesion), t.medidor_inicio) as current_meter
                    FROM sesiones_carga t 
                    JOIN cargadores c ON t.id_cargador = c.id_cargador
                    WHERE t.id_usuario = %s AND t.fecha_fin IS NULL 
                    ORDER BY t.fecha_inicio DESC LIMIT 1;
                """, (user_id,))
                row = cur.fetchone()
                
                # 3. Si no hay sesión activa, buscar si tiene una reserva vigente o próxima
                ocpp_id_cargador = "VC-0428" # Valor por defecto
                if row:
                    trans_id, start_time, meter_start, ocpp_id_cargador, current_meter = row
                    minutos = int((datetime.now(timezone.utc) - start_time).total_seconds() / 60)
                    kwh_consumidos = (float(current_meter) - float(meter_start)) / 1000.0
                    costo_estimado = round(kwh_consumidos * precio_kwh, 2)
                    
                    return {
                        "activa": True, 
                        "transaction_id": trans_id, 
                        "minutos": minutos,
                        "energia_kwh": round(kwh_consumidos, 2), 
                        "potencia_kw": 7.2,
                        "precio_por_kwh": precio_kwh,
                        "costo_estimado": costo_estimado,
                        "ocpp_id": ocpp_id_cargador
                    }
                else:
                    # Buscar cargador de la reserva más próxima del usuario
                    cur.execute("""
                        SELECT c.ocpp_id FROM reservas r
                        JOIN cargadores c ON r.id_cargador = c.id_cargador
                        WHERE r.id_usuario = %s AND r.estado IN ('Reservado', 'Activa')
                        ORDER BY r.fecha_inicio ASC LIMIT 1;
                    """, (user_id,))
                    res_row = cur.fetchone()
                    if res_row:
                        ocpp_id_cargador = res_row[0]

                    return {
                        "activa": False, 
                        "precio_por_kwh": precio_kwh,
                        "ocpp_id": ocpp_id_cargador
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