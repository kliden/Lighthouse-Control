import argparse, asyncio, pyperclip 
import lighthouse


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('state', choices=['on', 'off'], nargs='?', default='on',
                        help='Power state to set (on/off) (default = on)')
    parser.add_argument('addresses', type=str, nargs='*', help="The MAC addresses of the lighthouses to turn on/off")
    parser.add_argument('-s', '--scan', action='store_true', help="Scans and reports all lighthouses found.")
    args = parser.parse_args()

    if not args.scan and not args.addresses:
        print("If you aren't scanning (using the -s or --scan option) then you must supply the number of lighthouses.")
        return

    is_on = args.state.lower() == 'on'
    lighthouses = []
    completed_addresses = []
    try:
        try:
            print(f"Scanning for lighthouses for maximum of {str(lighthouse.SCAN_TIMEOUT)} seconds...")
            async for lh in lighthouse.Lighthouse.iter(lighthouse.SCAN_TIMEOUT):
                if lh not in lighthouses:
                    if args.scan or lh.address in args.addresses:
                        lighthouses.append(lh)
                    print(f"Found Name({lh.name}) - MAC({lh.address}) - RSSI({lh.rssi} dBm)")
                    if len(lighthouses) == len(args.addresses):
                        break
        except TimeoutError:
            if args.scan:
                pyperclip.copy(" ".join(l.address for l in lighthouses))
                print("Lighthouse MAC addresses copied to clipboard")

        if not args.scan:
            write_tasks = []
            for lh in lighthouses:
                print(f"{lh.address}: turning {'on' if is_on else 'off'}")
                t = asyncio.create_task(lh.write(is_on))
                write_tasks.append(t)

            for coro in asyncio.as_completed(write_tasks):
                lh = await coro
                print(f"{lh.address}: Done.")
                completed_addresses.append(lh.address)
    except Exception as e:
        print(str(e))
    finally:
        if not args.scan:
            if len(lighthouses) != len(args.addresses):
                print(f"Expected {len(args.addresses)} lighthouses, but found {len(lighthouses)}.")
            else:
                lighthouse_addresses = [lh.address for lh in lighthouses]
                missing_addresses = [n for n in lighthouse_addresses if n not in completed_addresses]
                for address in missing_addresses:
                    print(f"WARNING: {address} wasn't turned {'on' if is_on else 'off'}.")