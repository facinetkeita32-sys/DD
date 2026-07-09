@echo off
REM =============================================
REM  Build Shop With DD POS Standalone Executable
REM  Requires: Python, PyInstaller
REM =============================================
echo.
echo Building Shop With DD POS...
echo.

if "%1"=="--desktop" goto desktop
if "%1"=="--server" goto server

echo Usage: build.bat [--server ^| --desktop]
echo   --server   Build headless server EXE (runs in console)
echo   --desktop  Build desktop app EXE with native window (requires pywebview)
goto :eof

:server
echo Building server executable...
pyinstaller --onefile --name "ShopDD_POS_Server" --add-data "pos_system;pos_system" --hidden-import pos_system.main --hidden-import pos_system.api.routes --hidden-import pos_system.api.backup_routes --hidden-import pos_system.i18n.translator --hidden-import pos_system.services.receipt_service --hidden-import pos_system.services.backup_service --hidden-import pos_system.models.res_users --hidden-import pos_system.models.res_partner --hidden-import pos_system.models.res_currency --hidden-import pos_system.models.res_lang --hidden-import pos_system.models.res_company --hidden-import pos_system.models.product_product --hidden-import pos_system.models.product_category --hidden-import pos_system.models.pos_category --hidden-import pos_system.models.pos_order --hidden-import pos_system.models.pos_order_line --hidden-import pos_system.models.pos_session --hidden-import pos_system.models.pos_config --hidden-import pos_system.models.pos_payment_method --hidden-import pos_system.models.pos_tax --hidden-import pos_system.models.pos_payment --hidden-import pos_system.models.delivery_zone --hidden-import pos_system.odoo_orm --hidden-import pos_system.init_data --collect-all pos_system.i18n run.py
goto done

:desktop
echo Building desktop app executable...
pyinstaller --onefile --name "ShopDD_POS" --add-data "pos_system;pos_system" --hidden-import pos_system.main --hidden-import pos_system.api.routes --hidden-import pos_system.api.backup_routes --hidden-import pos_system.i18n.translator --hidden-import pos_system.services.receipt_service --hidden-import pos_system.services.backup_service --hidden-import pos_system.models.res_users --hidden-import pos_system.models.res_partner --hidden-import pos_system.models.res_currency --hidden-import pos_system.models.res_lang --hidden-import pos_system.models.res_company --hidden-import pos_system.models.product_product --hidden-import pos_system.models.product_category --hidden-import pos_system.models.pos_category --hidden-import pos_system.models.pos_order --hidden-import pos_system.models.pos_order_line --hidden-import pos_system.models.pos_session --hidden-import pos_system.models.pos_config --hidden-import pos_system.models.pos_payment_method --hidden-import pos_system.models.pos_tax --hidden-import pos_system.models.pos_payment --hidden-import pos_system.models.delivery_zone --hidden-import pos_system.odoo_orm --hidden-import pos_system.init_data --collect-all pos_system.i18n desktop_app.py
goto done

:done
echo.
echo Build complete! Check the "dist" folder.
pause
