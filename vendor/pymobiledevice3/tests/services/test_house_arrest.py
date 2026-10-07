import pytest
import pytest_asyncio

from pymobiledevice3.exceptions import AppNotInstalledError
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.services.house_arrest import HouseArrestService
from pymobiledevice3.services.installation_proxy import InstallationProxyService


@pytest_asyncio.fixture(scope="function")
async def user_bundle_id(lockdown: LockdownClient) -> str:
    async with InstallationProxyService(lockdown=lockdown) as installation_proxy:
        user_apps = await installation_proxy.get_apps(application_type="User")
    file_sharing_apps = [bundle_id for bundle_id, app_info in user_apps.items() if app_info.get("UIFileSharingEnabled")]
    if not file_sharing_apps:
        pytest.skip("No user apps with UIFileSharingEnabled installed to exercise house arrest")
    return file_sharing_apps[0]


@pytest.mark.asyncio
async def test_missing_bundle_id(lockdown: LockdownClient) -> None:
    with pytest.raises(AppNotInstalledError):
        async with await HouseArrestService.create(lockdown=lockdown, bundle_id="com.pymobiledevice3.missing.app"):
            pass


@pytest.mark.asyncio
async def test_vend_container_lists_app_root(lockdown: LockdownClient, user_bundle_id: str) -> None:
    async with await HouseArrestService.create(
        lockdown=lockdown, bundle_id=user_bundle_id, documents_only=True
    ) as service:
        await service.listdir("/Documents")
