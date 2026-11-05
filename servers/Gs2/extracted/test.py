import httpx
import asyncio

async def version_config():
    url = (
        "https://version.ggwhitehawk.com/live/ver.php"
        "?version=1.120.1"
        "&lang=en"
        "&device=android"
        "&channel=android"
        "&appstore=googleplay"
        "&region=BD"
        "&whitelist_version=1.7.0"
        "&whitelist_sp_version=1.0.0"
        "&device_name=asus%20ASUS_Z01QD"
        "&device_CPU=ARMv7%20VFPv3%20NEON"
        "&device_GPU=Adreno%20%28TM%29%20540"
        "&device_mem=7966"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        print("Code:", data.get("code"))
        print("Server open:", data.get("is_server_open"))
        print("Firewall open:", data.get("is_firewall_open"))
        print("Latest release:", data.get("latest_release_version"))
        print("Core URL:", data.get("core_url"))
        print("GOP URLs:", data.get("gop_url", "").split(";"))

        return data

    except httpx.TimeoutException:
        print("Request timed out")

    except httpx.HTTPError as e:
        print(f"HTTP error: {e}")

    except ValueError:
        print("Invalid JSON response")

    return None


async def main():
    data = await version_config()

    if data:
        print("Configuration fetched successfully")


if __name__ == "__main__":
    asyncio.run(main())