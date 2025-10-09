import os
import socket
import threading
import time
import asyncio
from dotenv import load_dotenv
from ..core.datastore import DATA_STORE
from ..core.mapping_store import SNMP_MAPPING
from threading import Event

# SNMP via pysnmp (support asyncore or asyncio carriers)
try:
    from pysnmp.carrier.asyncore.dgram import udp  # type: ignore
    _CARRIER = 'asyncore'
except Exception:  # pragma: no cover
    from pysnmp.carrier.asyncio.dgram import udp  # type: ignore
    _CARRIER = 'asyncio'
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.smi import builder, view, rfc1902, instrum

# Load environment variables
load_dotenv()


def _to_snmp_value(value, type_id: str):
    try:
        if type_id == 'Integer':
            return rfc1902.Integer(int(value))
        if type_id == 'OctetString':
            return rfc1902.OctetString(str(value))
        if type_id == 'Gauge32':
            return rfc1902.Gauge32(int(value))
        if type_id == 'Counter32':
            return rfc1902.Counter32(int(value))
        if type_id == 'Counter64':
            return rfc1902.Counter64(int(value))
        # default
        return rfc1902.OctetString(str(value))
    except Exception:
        return rfc1902.OctetString("0")


def snmp_server_thread(stop_event: Event):
    # Fix for asyncio event loop in thread
    if _CARRIER == 'asyncio':
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop in this thread, create a new one
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    
    host = os.getenv('SERVER_HOST', '0.0.0.0')
    port = int(os.getenv('SNMP_PORT', '1161'))

    snmp_engine = engine.SnmpEngine()

    # Transport: UDP server
    config.addTransport(
        snmp_engine,
        udp.domainName,
        udp.UdpTransport().openServerMode((host, port))
    )

    # v2c public
    config.addV1System(snmp_engine, 'public-area', 'public')
    config.addVacmUser(snmp_engine, 2, 'public-area', 'noAuthNoPriv', (1, 3, 6), (1, 3, 6))

    # Use the correct API method name for pysnmp 7.x
    try:
        mib_builder = snmp_engine.get_mib_builder()
    except AttributeError:
        # Fallback for older versions
        mib_builder = snmp_engine.getMibBuilder()
    
    mib_view = view.MibViewController(mib_builder)
    mib_instrum = instrum.MibInstrumController(mib_builder)

    # Responders
    cmdrsp.GetCommandResponder(snmp_engine)
    cmdrsp.NextCommandResponder(snmp_engine)

    enterprise_oid = SNMP_MAPPING.enterprise_oid

    print(f"✓ SNMP agent started on {host}:{port}")

    try:
        # Start dispatcher in background for request handling
        def run_dispatcher():
            try:
                snmp_engine.transportDispatcher.jobStarted(1)
                snmp_engine.transportDispatcher.runDispatcher()
            except Exception:
                try:
                    snmp_engine.transportDispatcher.closeDispatcher()
                except Exception:
                    pass

        if _CARRIER == 'asyncore':
            threading.Thread(target=run_dispatcher, daemon=True).start()
        else:
            # asyncio carrier integrates with event loop; start in thread too
            threading.Thread(target=run_dispatcher, daemon=True).start()

        while not stop_event.is_set():
            # Refresh scalars under enterprise OID
            maps = SNMP_MAPPING.all()
            for data_id, meta in maps.items():
                key = str(meta['key'])
                suffix = int(meta['oid_suffix'])
                type_id = str(meta['type'])
                oid = enterprise_oid + (suffix,)
                value = DATA_STORE.read(key)
                snmp_val = _to_snmp_value(value, type_id)
                try:
                    mib_instrum.writeVars(((oid, snmp_val),))
                except Exception:
                    # Initialize and retry once
                    try:
                        mib_instrum.mibBuilder.importSymbols('SNMPv2-SMI', 'iso')
                        mib_instrum.writeVars(((oid, snmp_val),))
                    except Exception:
                        pass

            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            snmp_engine.transportDispatcher.closeDispatcher()
        except Exception:
            pass
