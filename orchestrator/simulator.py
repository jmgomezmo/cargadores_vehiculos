import asyncio
import logging
import websockets
from datetime import datetime, timezone
from ocpp.v16 import ChargePoint as cp
from ocpp.v16 import call, call_result
from ocpp.v16.enums import Action, RegistrationStatus, ChargePointStatus, ChargePointErrorCode, RemoteStartStopStatus
from ocpp.routing import on

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

class ChargePointSimulator(cp):
    def __init__(self, id, connection):
        super().__init__(id, connection)
        self.transaction_id = None
        self.is_charging = False
        self.meter_value = 0

    async def send_boot_notification(self):
        request = call.BootNotification(
            charge_point_vendor="Delta Electronics", charge_point_model="AC MAX Pro", firmware_version="2.0.0-adv"
        )
        response = await self.call(request)
        if response.status == RegistrationStatus.accepted:
            logging.info("✅ Cargador iniciado y aceptado.")
            await self.send_status_notification(ChargePointStatus.available)
            asyncio.create_task(self.heartbeat_loop())

    async def send_status_notification(self, status):
        request = call.StatusNotification(connector_id=1, error_code=ChargePointErrorCode.no_error, status=status)
        await self.call(request)

    async def heartbeat_loop(self):
        while True:
            try:
                await self.call(call.Heartbeat())
                await asyncio.sleep(30)
            except Exception:
                break

    @on(Action.remote_start_transaction)
    async def on_remote_start_transaction(self, id_tag, **kwargs):
        logging.info(f"\n⚡ ORDEN RECIBIDA: Inicio Remoto (Tag: {id_tag})")
        asyncio.create_task(self.start_transaction(id_tag))
        return call_result.RemoteStartTransaction(status=RemoteStartStopStatus.accepted)

    async def start_transaction(self, id_tag):
        await self.send_status_notification(ChargePointStatus.charging)
        request = call.StartTransaction(
            connector_id=1, id_tag=id_tag, meter_start=self.meter_value, timestamp=datetime.now(timezone.utc).isoformat()
        )
        response = await self.call(request)
        if response.id_tag_info.get('status') == 'Accepted':
            self.transaction_id = response.transaction_id
            self.is_charging = True
            logging.info(f"▶️ Transacción {self.transaction_id} autorizada.")
            asyncio.create_task(self.meter_values_loop())
        else:
            await self.send_status_notification(ChargePointStatus.available)

    async def meter_values_loop(self):
        # Aseguramos el ID en una variable local para que no lo borre la orden de apagado
        tx_id_actual = self.transaction_id 
        
        while self.is_charging:
            await asyncio.sleep(5)
            
            # Si la orden de detener llegó mientras dormía, aborta el envío
            if not self.is_charging:
                break 
                
            self.meter_value += 150
            meter_payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sampled_value": [{"value": str(self.meter_value), "context": "Sample.Periodic", "format": "Raw", "measurand": "Energy.Active.Import.Register", "location": "Outlet", "unit": "Wh"}]
            }
            await self.call(call.MeterValues(connector_id=1, transaction_id=tx_id_actual, meter_value=[meter_payload]))
            logging.info(f"🔋 Telemetría: {self.meter_value} Wh consumidos.")

    @on(Action.remote_stop_transaction)
    async def on_remote_stop_transaction(self, transaction_id, **kwargs):
        logging.info(f"\n⏹️ ORDEN RECIBIDA: Detener carga remota (Tx: {transaction_id})")
        self.is_charging = False 
        asyncio.create_task(self.stop_transaction(transaction_id))
        return call_result.RemoteStopTransaction(status=RemoteStartStopStatus.accepted)

    async def stop_transaction(self, transaction_id):
        request = call.StopTransaction(
            meter_stop=int(self.meter_value), timestamp=datetime.now(timezone.utc).isoformat(), transaction_id=transaction_id
        )
        await self.call(request)
        await self.send_status_notification(ChargePointStatus.available)
        self.transaction_id = None
        logging.info("Carga finalizada exitosamente. Cargador Disponible.")

async def main():
    url = "ws://107.23.142.61:8080/CP_AVANZADO_01"
    while True:
        try:
            async with websockets.connect(url, subprotocols=['ocpp1.6']) as ws:
                cp_simulator = ChargePointSimulator('CP_AVANZADO_01', ws)
                logging.info("🔗 Conectado a AWS. Listo para operar.")
                await asyncio.gather(cp_simulator.start(), cp_simulator.send_boot_notification())
        except websockets.exceptions.ConnectionClosed:
            logging.warning("⚠️ Conexión perdida. Reintentando en 5 segundos...")
            await asyncio.sleep(5)
        except Exception as e:
            logging.error(f"❌ Fallo crítico de red: {e}. Reintentando...")
            await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())