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

class CancelReservationRequest(BaseModel):
    reservation_id: int

@app.post("/api/reservar/cancelar")
def cancelar_reserva(req: CancelReservationRequest):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE reservas 
                    SET estado = 'Cancelada' 
                    WHERE id_reserva = %s;
                """, (req.reservation_id,))
                conn.commit()
        return {"status": "success", "message": "Reserva cancelada correctamente"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/reservar")
def crear_reserva(req: ReservationRequest):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 1. Validar si el cargador ya tiene una reserva cruzada en ese horario
                cur.execute("""
                    SELECT id_reserva FROM reservas 
                    WHERE id_cargador = %s 
                      AND estado IN ('Reservado', 'Activa')
                      AND (
                          (%s < fecha_fin) AND (%s > fecha_inicio)
                      );
                """, (req.charge_point_id, req.start_time, req.end_time))
                
                conflicto = cur.fetchone()
                if conflicto:
                    raise HTTPException(
                        status_code=400, 
                        detail="El cargador ya se encuentra reservado en esta franja horaria por otro usuario."
                    )

                # 2. Si no hay cruce, proceder con la inserción
                cur.execute("""
                    INSERT INTO reservas (id_usuario, id_cargador, fecha_inicio, fecha_fin, estado)
                    VALUES (%s, %s, %s, %s, 'Reservado') RETURNING id_reserva;
                """, (req.user_id, req.charge_point_id, req.start_time, req.end_time))
                res_id = cur.fetchone()[0]
                conn.commit()
                
        return {"status": "success", "ticket_reserva": f"RES-{res_id}", "id_reserva": res_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/iniciar_carga")
def iniciar_carga(req: StartChargeRequest):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # 1. Validar estrictamente si el usuario tiene una reserva válida (Reservado o Activa)
                cur.execute("""
                    SELECT id_reserva FROM reservas 
                    WHERE id_usuario = %s AND id_cargador = %s AND estado IN ('Reservado', 'Activa')
                    LIMIT 1;
                """, (req.user_id, req.charge_point_id))
                reserva_valida = cur.fetchone()

                if not reserva_valida:
                    raise HTTPException(
                        status_code=403, 
                        detail="Acción no permitida: Debe realizar una reserva previa para iniciar la carga."
                    )

                # 2. Extracción del id_tag real
                cur.execute("SELECT id_tag FROM usuarios WHERE id_usuario = %s;", (req.user_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Usuario no encontrado")
                id_tag_usuario = row[0]

                # 3. Cambiar estado de reserva a 'Activa'
                cur.execute("""
                    UPDATE reservas 
                    SET estado = 'Activa' 
                    WHERE id_usuario = %s AND id_cargador = %s AND estado = 'Reservado';
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
        # 1. Enviar el comando físico al orquestador OCPP / Simulador
        payload_ocpp = {"charge_point_id": f"CP_AVANZADO_0{req.charge_point_id}"}
        respuesta = requests.post("http://127.0.0.1:9090/remote_stop", json=payload_ocpp)
        
        if respuesta.status_code != 200:
            err_msg = respuesta.json().get("error", "Error en hardware al intentar detener la carga")
            raise HTTPException(status_code=400, detail=err_msg)
        
        # 2. Si el cargador se detuvo correctamente, actualizamos PostgreSQL
        with get_db() as conn:
            with conn.cursor() as cur:
                # Finalizar la sesión de carga activa
                cur.execute("""
                    UPDATE ocpp.sesiones_carga
                    SET fecha_fin = CURRENT_TIMESTAMP
                    WHERE id_usuario = %s 
                      AND id_cargador = %s 
                      AND fecha_fin IS NULL;
                """, (req.user_id, req.charge_point_id))
                
                # Truncar la reserva activa para liberar el tiempo restante
                cur.execute("""
                    UPDATE ocpp.reservas
                    SET fecha_fin = CURRENT_TIMESTAMP, 
                        estado = 'Completada'
                    WHERE id_usuario = %s 
                      AND id_cargador = %s 
                      AND estado = 'Activa';
                """, (req.user_id, req.charge_point_id))
                
                conn.commit()
                
        return {"status": "success", "message": "Carga detenida y tiempo de reserva restante liberado."}
    
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
                cur.execute("""
                    SELECT precio_por_kwh FROM tarifas 
                    WHERE valido_desde <= CURRENT_TIMESTAMP 
                      AND (valido_hasta IS NULL OR valido_hasta >= CURRENT_TIMESTAMP)
                    ORDER BY valido_desde DESC LIMIT 1;
                """)
                tarifa_row = cur.fetchone()
                precio_kwh = float(tarifa_row[0]) if tarifa_row else 1850.0

                ocpp_id_cargador = "VC-0428"

                # Verificar si tiene reserva válida vigente
                cur.execute("""
                    SELECT 1 FROM reservas 
                    WHERE id_usuario = %s AND estado IN ('Reservado', 'Activa')
                    LIMIT 1;
                """, (user_id,))
                tiene_reserva = cur.fetchone() is not None

                cur.execute("""
                    SELECT t.id_sesion, t.fecha_inicio, t.medidor_inicio, c.ocpp_id,
                           COALESCE((SELECT MAX(CAST(valor AS NUMERIC)) FROM telemetria WHERE id_sesion = t.id_sesion), t.medidor_inicio) as current_meter
                    FROM sesiones_carga t 
                    JOIN cargadores c ON t.id_cargador = c.id_cargador
                    WHERE t.id_usuario = %s AND t.fecha_fin IS NULL 
                    ORDER BY t.fecha_inicio DESC LIMIT 1;
                """, (user_id,))
                row = cur.fetchone()
                
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
                        "ocpp_id": ocpp_id_cargador,
                        "tiene_reserva": True
                    }
                else:
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
                        "ocpp_id": ocpp_id_cargador,
                        "tiene_reserva": tiene_reserva
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

@app.get("/api/reservas/disponibilidad/{charge_point_id}")
def obtener_disponibilidad(charge_point_id: int, fecha: str):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Consultar las horas de inicio de reservas activas/reservadas para ese día y cargador
                cur.execute("""
                    SELECT TO_CHAR(fecha_inicio AT TIME ZONE 'UTC', 'HH24:MI') as hora_inicio
                    FROM reservas
                    WHERE id_cargador = %s 
                      AND estado IN ('Reservado', 'Activa')
                      AND TO_CHAR(fecha_inicio AT TIME ZONE 'UTC', 'YYYY-MM-DD') = %s;
                """, (charge_point_id, fecha))
                rows = cur.fetchall()
                horas_ocupadas = [row[0] for row in rows]
                return {"ocupadas": horas_ocupadas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ubicacion/{charge_point_id}")
def obtener_ubicacion(charge_point_id: int):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Si tienes relación entre cargadores y ubicaciones, ajusta el JOIN. 
                # Por defecto tomaremos el primer registro de la tabla.
                cur.execute("SELECT nombre FROM ocpp.ubicaciones LIMIT 1;")
                row = cur.fetchone()
                if row:
                    return {"nombre": row[0]}
                return {"nombre": "Comunidad Volta Blue"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))