# Wompi Sandbox con Django local y ngrok

Esta guía usa exclusivamente Wompi Sandbox. No copies secretos al repositorio.

## Requisitos

- Django debe usar una base local de desarrollo o una rama aislada de Neon.
- El checkout se habilita explícitamente con `WOMPI_CHECKOUT_ENABLED=True`.
- Las cuatro credenciales Sandbox permanecen únicamente en `.env`.
- ngrok está instalado. Si una terminal abierta antes de instalarlo no lo reconoce, ciérrala y abre PowerShell nuevamente.

## Configuración local

1. Autentica ngrok desde tu propia terminal. No compartas el token:

   ```powershell
   ngrok config add-authtoken TU_TOKEN_PERSONAL
   ```

2. Inicia Django:

   ```powershell
   cd C:\Projects\Proyecto-Grado-Repo
   .\.venv\Scripts\Activate.ps1
   python manage.py runserver 127.0.0.1:8000
   ```

3. En otra terminal inicia el túnel:

   ```powershell
   ngrok http 8000
   ```

4. Copia únicamente el origen HTTPS mostrado por ngrok. En tu `.env` local agrega, por ejemplo:

   ```dotenv
   LOCAL_TUNNEL_URL=https://example.ngrok-free.dev
   ```

   El valor real debe ser HTTPS, no puede contener ruta y solo se acepta con `DEBUG=True`. Reinicia Django después de cambiarlo.

## Wompi Sandbox

En el Dashboard de Wompi Sandbox configura la URL de eventos:

```text
https://DOMINIO-NGROK/reservas/wompi/webhook/
```

No configures esta URL en producción. El formulario enviará como retorno:

```text
https://DOMINIO-NGROK/reservas/wompi/resultado/ID_RESERVA/
```

Wompi añadirá el parámetro `id` de la transacción. Cancha Lista consulta ese ID desde el backend y valida referencia, monto, moneda y pertenencia antes de actualizar datos. El webhook firmado sigue siendo el mecanismo principal.

## Comprobaciones seguras

Con Django y ngrok activos:

```powershell
Invoke-WebRequest -Method Get -Uri https://DOMINIO-NGROK/reservas/wompi/webhook/ -SkipHttpErrorCheck
Invoke-WebRequest -Method Post -ContentType application/json -Body '{}' -Uri https://DOMINIO-NGROK/reservas/wompi/webhook/ -SkipHttpErrorCheck
```

Los resultados esperados son 405 para GET y 400 para un POST sin firma. Esto no demuestra que Wompi haya entregado un evento auténtico.

## Prueba manual controlada

1. Crea una reserva diferente para cada escenario.
2. Abre el checkout y realiza una sola transacción Sandbox.
3. Regresa usando el flujo de Wompi.
4. Comprueba en la interfaz que una aprobación solo aparece después de verificarse.
5. Para revisar sin modificar datos:

   ```powershell
   python manage.py shell
   ```

   En el shell consulta por una referencia o ID que ya conozcas; no enumeres credenciales ni variables de entorno.

6. Para reservas antiguas ejecuta el diagnóstico de solo lectura:

   ```powershell
   python manage.py wompi_expiration_report
   ```

   - `CAN_EXPIRE`: no hay evidencia financiera pendiente.
   - `NEEDS_RECONCILIATION`: existe un intento o transacción sin resultado final.
   - `FINANCIAL_REVIEW`: existe aprobación o excepción financiera.
   - `NOT_ELIGIBLE`: la reserva no cumple las condiciones del reporte.

No cambies estados manualmente. Primero concilia los IDs conocidos contra Wompi; los intentos sin ID requieren revisión administrativa y no deben asumirse rechazados.

## Cierre

Detén Django y ngrok con `Ctrl+C` en cada terminal. El dominio temporal deja de estar disponible. Si no volverás a usarlo, elimina manualmente `LOCAL_TUNNEL_URL` de tu `.env`; nunca publiques ese archivo.
