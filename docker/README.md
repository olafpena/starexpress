# Entorno local (Docker)

ERPNext v16.37.0 con la app `taller` de este repo. Sitio `frontend` en
http://localhost:8080 (usuario `Administrator`, contraseña `admin`).

## Levantar

```bash
cd docker
docker compose up -d --build
docker compose logs -f create-site   # espera a que termine con código 0
```

`create-site` crea el sitio `frontend` con ERPNext y `taller` si no existe; si ya
existe, instala `taller` cuando falte y corre `bench migrate`.

El código de la app se monta desde la raíz del repo en `apps/taller` de todos los
servicios de Frappe. Con `developer_mode`, lo que se edita en el Desk (DocTypes,
workspaces) queda en este repo: haz commit y push aquí.

| Cambio | Qué correr |
|---|---|
| Código Python | `docker compose restart backend queue-short queue-long scheduler` |
| DocTypes o patches | `docker compose exec backend bench --site frontend migrate` |
| JS o CSS de `taller/public` | `docker compose exec backend bench build --app taller` |
| Dependencias, `Containerfile` o versión de ERPNext | `docker compose up -d --build` |

## Datos

La base de datos y los archivos del sitio están en los volúmenes
`frappe_docker_db-data` y `frappe_docker_sites` (el nombre viene del repo anterior).
`docker compose down` los conserva; **no uses `docker compose down -v`**, que los
borra. Respaldo:

```bash
docker compose exec backend bench --site frontend backup --with-files
```

## Pruebas

```bash
docker compose exec backend bench --site frontend execute taller.tests.regresion.correr
```

## Actualizar ERPNext

Cambia `BASE_IMAGE` en `Containerfile` y la etiqueta `taller-local:v16.xx.x` en
`compose.yml`, luego `docker compose up -d --build`.
