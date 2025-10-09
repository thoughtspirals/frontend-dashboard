#!/usr/bin/env python3
"""
Standalone Data-Service Sync Runner

This script runs the Data-Service sync service independently.
It continuously reads values from the polling service and syncs them
to Data-Service via IPC (Unix socket).

Usage:
    python sync_runner.py [options]
    
Options:
    --socket-path PATH    Path to IPC socket (default: /tmp/dataservice.sock)
    --interval SECONDS    Sync interval in seconds (default: 1.0)
    --no-logging          Disable logging
    --stats-interval SEC  Print stats every N seconds (default: 60)
"""

import sys
import os
import time
import signal
import argparse

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dataservice.core.dataservice_sync import DataServiceSyncService


def main():
    parser = argparse.ArgumentParser(
        description='Data-Service Sync Runner - Syncs polling data to Data-Service via IPC'
    )
    parser.add_argument(
        '--socket-path',
        type=str,
        default='/tmp/dataservice.sock',
        help='Path to Data-Service IPC socket (default: /tmp/dataservice.sock)'
    )
    parser.add_argument(
        '--interval',
        type=float,
        default=1.0,
        help='Sync interval in seconds (default: 1.0)'
    )
    parser.add_argument(
        '--no-logging',
        action='store_true',
        help='Disable logging'
    )
    parser.add_argument(
        '--stats-interval',
        type=int,
        default=60,
        help='Print stats every N seconds (default: 60)'
    )
    
    args = parser.parse_args()
    
    # Create sync service
    sync_service = DataServiceSyncService(
        socket_path=args.socket_path,
        sync_interval=args.interval,
        enable_logging=not args.no_logging
    )
    
    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print("\n🛑 Shutting down Data-Service sync...")
        sync_service.stop()
        print("✓ Sync service stopped")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start the sync service
    print("=" * 70)
    print("Data-Service Sync Runner")
    print("=" * 70)
    print(f"Socket Path:     {args.socket_path}")
    print(f"Sync Interval:   {args.interval}s")
    print(f"Logging:         {'Enabled' if not args.no_logging else 'Disabled'}")
    print(f"Stats Interval:  {args.stats_interval}s")
    print("=" * 70)
    print()
    
    success = sync_service.start()
    
    if not success:
        print("❌ Failed to start sync service (already running?)")
        sys.exit(1)
    
    print("✅ Sync service started successfully")
    print("📊 Monitoring... (Press Ctrl+C to stop)")
    print()
    
    # Monitor and print stats
    last_stats_time = time.time()
    
    try:
        while True:
            time.sleep(1)
            
            current_time = time.time()
            if current_time - last_stats_time >= args.stats_interval:
                stats = sync_service.get_stats()
                print(f"\n📊 Stats at {time.strftime('%Y-%m-%d %H:%M:%S')}:")
                print(f"   Total Syncs:       {stats['total_syncs']}")
                print(f"   Successful Writes: {stats['successful_writes']}")
                print(f"   Failed Writes:     {stats['failed_writes']}")
                print(f"   Running:           {stats['running']}")
                
                if stats['last_sync_time']:
                    last_sync = time.strftime('%H:%M:%S', time.localtime(stats['last_sync_time']))
                    print(f"   Last Sync:         {last_sync}")
                
                # Print recent errors if any
                if stats['errors']:
                    recent_errors = stats['errors'][-5:]  # Last 5 errors
                    print(f"   Recent Errors ({len(stats['errors'])} total):")
                    for err in recent_errors:
                        err_time = time.strftime('%H:%M:%S', time.localtime(err['time']))
                        print(f"     [{err_time}] {err['message']}")
                
                print()
                last_stats_time = current_time
                
    except KeyboardInterrupt:
        print("\n🛑 Received interrupt, stopping...")
        sync_service.stop()
        print("✓ Sync service stopped gracefully")


if __name__ == "__main__":
    main()
