"""Pruebas de dominio, permisos y persistencia de OficiosYa.

Si TEST_DATABASE_URL apunta a PostgreSQL, el nombre debe terminar en ``_test``.
El setUp elimina y recrea las tablas de esa base de pruebas. Nunca se usa
DATABASE_URL ni se permite apuntar por error a la base oficiosya principal.
"""
from datetime import date
import os
import unittest
from uuid import uuid4
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

import app as app_module
from app import create_app
from config import TestConfig
from db_models import (
    Administrador, CategoriaServicio, Cliente, Empresa, Oficio, Postulacion,
    Proyecto, Solicitud, SolicitudOficio, Trabajador, Usuario, Zona,
)
from extensions import db
from modelos import ErrorDominio, Plataforma, seed_referencias
from estructuras import AccionReversible, ColaFIFO, ListaEnlazada, PilaLIFO, TablaHash


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "sqlite://")
_test_url = make_url(TEST_DATABASE_URL)
if _test_url.get_backend_name() == "postgresql":
    if not (_test_url.database or "").lower().endswith("_test"):
        raise RuntimeError("Las pruebas destructivas solo pueden usar una base PostgreSQL cuyo nombre termine en _test.")
    if (_test_url.database or "").lower() == "oficiosya":
        raise RuntimeError("TEST_DATABASE_URL no puede apuntar a la base principal oficiosya.")


class IsolatedTestConfig(TestConfig):
    SECRET_KEY = "solo-pruebas-no-usar-en-produccion"
    SQLALCHEMY_DATABASE_URI = TEST_DATABASE_URL
    WTF_CSRF_ENABLED = False
    TESTING = True


class EstructurasTests(unittest.TestCase):
    def test_lista_enlazada_y_tabla_hash(self):
        lista = ListaEnlazada()
        lista.agregar("A")
        lista.agregar("B")
        self.assertEqual(lista.buscar(lambda x: x == "B"), "B")
        self.assertEqual(lista.eliminar(lambda x: x == "A"), "A")
        self.assertEqual(list(lista), ["B"])

        tabla = TablaHash(capacidad=2)
        objetos = [object() for _ in range(12)]
        for indice, objeto in enumerate(objetos):
            tabla.insertar(f"ID-{indice}", objeto)
        self.assertGreater(tabla.capacidad, 2)
        for indice, objeto in enumerate(objetos):
            self.assertIs(tabla.buscar(f"ID-{indice}"), objeto)
        self.assertIs(tabla.eliminar("ID-3"), objetos[3])
        self.assertIsNone(tabla.buscar("ID-3"))

    def test_cola_fifo_y_pila_lifo(self):
        cola = ColaFIFO()
        cola.encolar("primero")
        cola.encolar("segundo")
        self.assertEqual(cola.desencolar(), "primero")
        pila = PilaLIFO()
        pila.apilar(AccionReversible("a", lambda: True))
        pila.apilar(AccionReversible("b", lambda: True))
        self.assertEqual(pila.desapilar().descripcion, "b")


class OficiosYaTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(IsolatedTestConfig)
        self.context = self.app.app_context()
        self.context.push()
        db.session.remove()
        # Solo se borran tablas en la URL de pruebas; PostgreSQL tiene guardia _test arriba.
        db.drop_all()
        db.create_all()
        seed_referencias()
        self.plataforma = self.app.extensions["oficiosya_plataforma"]
        self.plataforma.reconstruir_indices()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def oficio_id(self, nombre):
        return db.session.scalar(select(Oficio.id).where(Oficio.nombre == nombre))

    def zona_id(self, nombre):
        return db.session.scalar(select(Zona.id).where(Zona.nombre == nombre))

    def crear_cliente(self, correo="cliente@example.test"):
        return self.plataforma.registrar_cliente("Carla", "Demo", correo, "098100000", "clave-demo-2026")

    def crear_trabajador(self, correo="trabajador@example.test", oficios=None, zonas=None, categorias=None):
        oficios = oficios or [self.oficio_id("Electricidad")]
        zonas = zonas or [self.zona_id("Asunción")]
        categorias = categorias or ["hogar", "empresarial"]
        return self.plataforma.registrar_trabajador(
            "Tomás", "Demo", correo, "098200000", "clave-demo-2026",
            oficios, zonas, categorias, "Profesional de demostración", "Asunción", 4,
        )

    def crear_administrador(self):
        admin = Administrador(
            nombre="Ada", apellido="Admin", correo="admin@example.test",
            telefono="098300000", activo=True,
        )
        admin.set_password("clave-admin-2026")
        db.session.add(admin)
        db.session.flush()
        admin.public_id = f"ADM-{admin.id:06d}"
        db.session.commit()
        return admin

    def crear_empresa(self, correo="empresa@example.test", ruc="80000001-1"):
        return self.plataforma.registrar_empresa(
            "Elena", "Demo", correo, "098400000", "clave-empresa-2026",
            "Empresa Demo", ruc, "Asunción", "021000000", correo,
            "Perfil empresarial de prueba",
        )

    def crear_proyecto(self, empresa, nombre="Reforma de oficina"):
        return Plataforma.crear_proyecto(
            empresa,
            {
                "nombre": nombre,
                "descripcion": "Trabajo de prueba para validar el flujo.",
                "trabajadores_necesarios": 2,
                "ubicacion": "Asunción",
                "inicio_estimado": date(2027, 2, 1),
                "duracion_dias": 20,
                "presupuesto": None,
                "estado": "abierto",
            },
            [self.oficio_id("Electricidad")],
        )

    def login(self, usuario, password="clave-demo-2026"):
        return self.client.post(
            "/acceso", data={"identificador": usuario.correo, "password": password},
            follow_redirects=True,
        )

    def test_registro_hash_ids_unicos_y_busqueda_hash(self):
        primero = self.crear_cliente("uno@example.test")
        segundo = self.crear_cliente("dos@example.test")
        self.assertNotEqual(primero.public_id, segundo.public_id)
        self.assertTrue(primero.public_id.startswith("CLI-"))
        self.assertNotEqual(primero.password_hash, "clave-demo-2026")
        self.assertTrue(primero.check_password("clave-demo-2026"))
        self.assertIs(self.plataforma.buscar_usuario(primero.public_id), primero)
        self.assertIs(self.plataforma.buscar_usuario("UNO@example.test"), primero)

    def test_arbol_busca_descendientes_y_bfs_zonas(self):
        self.plataforma.reconstruir_indices()
        self.assertIn("Electricidad", self.plataforma.arbol.descendientes("Instalaciones"))
        distancias = self.plataforma.grafo.bfs("Asunción", 1)
        self.assertEqual(distancias["Asunción"], 0)
        self.assertEqual(distancias["Lambaré"], 1)
        self.assertEqual(distancias["Fernando de la Mora"], 1)
        self.assertNotIn("Capiatá", distancias)

    def test_trabajador_multiple_oficio_categoria_y_busqueda_bfs(self):
        worker = self.crear_trabajador(
            oficios=[self.oficio_id("Electricidad"), self.oficio_id("Plomería")],
            zonas=[self.zona_id("Lambaré")], categorias=["empresarial"],
        )
        resultados = self.plataforma.trabajadores_disponibles(
            self.oficio_id("Instalaciones"), "Asunción", True, "empresarial",
        )
        self.assertIn(worker, [resultado[0] for resultado in resultados])
        self.assertEqual(next(x for x in resultados if x[0] == worker)[1], 1)
        hogar = self.plataforma.trabajadores_disponibles(
            self.oficio_id("Electricidad"), "Asunción", True, "hogar",
        )
        self.assertNotIn(worker, [resultado[0] for resultado in hogar])
        customer = self.crear_cliente()
        with self.assertRaisesRegex(ErrorDominio, "zona de cobertura"):
            self.plataforma.crear_solicitud(
                customer, worker, "Trabajo en zona no cubierta", self.oficio_id("Electricidad"),
                zona_id=self.zona_id("Asunción"), categorias=["empresarial"],
            )
        self.plataforma.actualizar_oficios(worker, [self.oficio_id("Pintura")])
        self.assertEqual([o.nombre for o in worker.oficios], ["Pintura"])

    def test_propuesta_oficio_similitud_aprobacion_y_rechazo(self):
        worker = self.crear_trabajador()
        admin = self.crear_administrador()
        proposal = self.plataforma.solicitar_oficio(worker, "Cerrajería", "Apertura y reparación de cerraduras.")
        self.assertEqual(proposal.estado, "pendiente")
        with self.assertRaises(ErrorDominio):
            self.plataforma.solicitar_oficio(worker, "cerrajeria", "Propuesta duplicada.")
        self.plataforma.resolver_solicitud_oficio(proposal, admin, "aprobado")
        self.assertEqual(proposal.estado, "aprobado")
        self.assertIsNotNone(db.session.scalar(select(Oficio.id).where(Oficio.nombre_normalizado == "cerrajeria")))

        rejected = self.plataforma.solicitar_oficio(worker, "Instalación de toldos", "Montaje y reparación de toldos.")
        self.plataforma.resolver_solicitud_oficio(rejected, admin, "rechazado")
        self.assertEqual(rejected.estado, "rechazado")
        self.assertIsNone(db.session.scalar(select(Oficio.id).where(Oficio.nombre_normalizado == "instalacion de toldos")))

    def test_fifo_estados_y_valoracion_unica(self):
        customer = self.crear_cliente()
        worker = self.crear_trabajador()
        first = self.plataforma.crear_solicitud(customer, worker, "Reparar el tablero", self.oficio_id("Electricidad"), categorias=["hogar"])
        second = self.plataforma.crear_solicitud(customer, worker, "Cambiar una canilla", self.oficio_id("Electricidad"), categorias=["hogar"])
        with self.assertRaisesRegex(ErrorDominio, first.public_id):
            self.plataforma.atender_siguiente(worker, second.public_id)
        self.assertEqual(first.estado, "pendiente")
        self.plataforma.atender_siguiente(worker, first.public_id)
        self.plataforma.cambiar_estado(first, "finalizada", actor=worker)
        with self.assertRaises(ErrorDominio):
            self.plataforma.cambiar_estado(first, "cancelada", actor=worker)
        self.assertEqual(second.estado, "pendiente")
        self.plataforma.valorar(customer, first, 4, "Buen trabajo")
        self.assertEqual(worker.promedio, 4.0)
        with self.assertRaises(ErrorDominio):
            self.plataforma.valorar(customer, first, 5, "Duplicada")

    def test_pila_deshace_solo_accion_compatible(self):
        customer = self.crear_cliente()
        worker = self.crear_trabajador()
        service = self.plataforma.crear_solicitud(customer, worker, "Revisar toma", self.oficio_id("Electricidad"), categorias=["hogar"])
        admin = self.crear_administrador()
        with self.assertRaisesRegex(ErrorDominio, "otra cuenta"):
            self.plataforma.deshacer(admin.id)
        self.assertIsNotNone(db.session.get(Solicitud, service.id))
        descripcion = self.plataforma.deshacer(customer.id)
        self.assertIn(service.public_id, descripcion)
        self.assertIsNone(db.session.get(Solicitud, service.id))
        with self.assertRaises(ErrorDominio):
            self.plataforma.deshacer(customer.id)

    def test_empresa_proyecto_postulacion_y_permiso_de_propiedad(self):
        empresa = self.crear_empresa()
        otro = self.crear_empresa("otra@example.test", "80000002-9")
        worker = self.crear_trabajador()
        project = self.crear_proyecto(empresa)
        application = Plataforma.postular(worker, project)
        self.assertEqual(application.estado, "pendiente")
        with self.assertRaises(ErrorDominio):
            Plataforma.postular(worker, project)
        with self.assertRaises(ErrorDominio):
            Plataforma.resolver_postulacion(otro, application, "aceptada")
        Plataforma.resolver_postulacion(empresa, application, "aceptada")
        self.assertEqual(application.estado, "aceptada")

        with self.assertRaises(ErrorDominio):
            Plataforma.actualizar_proyecto(otro, project, {"nombre": "Intrusión"}, [self.oficio_id("Electricidad")])

    def test_editar_proyecto_conserva_estado_y_protege_propietario_en_rutas(self):
        company = self.crear_empresa()
        other = self.crear_empresa("otra@example.test", "80000002-9")
        project = self.crear_proyecto(company)
        project.estado = "en_proceso"
        db.session.commit()

        self.login(company, "clave-empresa-2026")
        response = self.client.post(f"/empresa/proyectos/{project.id}/editar", data={
            "nombre": "Reforma actualizada", "descripcion": "Descripción actualizada.",
            "oficios": [str(self.oficio_id("Electricidad"))],
            "trabajadores_necesarios": "3", "ubicacion": "San Lorenzo",
            "inicio_estimado": "2027-03-01", "duracion_dias": "25", "presupuesto": "",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(db.session.get(Proyecto, project.id).estado, "en_proceso")
        self.client.post("/salir")
        self.login(other, "clave-empresa-2026")
        self.assertEqual(self.client.get(f"/empresa/proyectos/{project.id}/editar").status_code, 403)
        self.assertEqual(self.client.post(f"/empresa/proyectos/{project.id}/estado", data={"estado": "finalizado"}).status_code, 403)

    def test_rutas_render_registro_y_permisos_backend(self):
        for path in ("/", "/registro", "/acceso", "/empresas", "/proyectos", "/health"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        response = self.client.post("/registro", data={
            "tipo": "trabajador", "nombre": "Nora", "apellido": "Prueba",
            "correo": "nora@example.test", "telefono": "098500000",
            "password": "clave-trabajo-2026", "oficios": [str(self.oficio_id("Pintura"))],
            "zonas": [str(self.zona_id("Asunción"))], "categorias": ["hogar", "empresarial"],
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        created = db.session.scalar(select(Trabajador).where(Trabajador.correo == "nora@example.test"))
        self.assertIsNotNone(created)
        self.assertTrue(created.public_id.startswith("TRA-"))

        self.client.get("/salir")  # GET no cierra sesión: el endpoint solo acepta POST.
        self.client.post("/salir", follow_redirects=True)
        self.assertEqual(self.client.get("/admin/oficios").status_code, 302)
        self.assertEqual(self.client.get("/academico").status_code, 302)
        customer = self.crear_cliente()
        self.login(customer)
        self.assertEqual(self.client.get("/admin/oficios").status_code, 403)
        self.assertEqual(self.client.get("/academico").status_code, 403)
        self.client.post("/salir")
        admin = self.crear_administrador()
        self.login(admin, "clave-admin-2026")
        self.assertEqual(self.client.get("/academico").status_code, 200)

    def test_inicio_sesion_por_correo_y_identificador(self):
        customer = self.crear_cliente()
        response = self.client.post("/acceso", data={"identificador": customer.correo, "password": "clave-demo-2026"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sesión iniciada".encode(), response.data)
        self.client.post("/salir")
        response = self.client.post("/acceso", data={"identificador": customer.public_id, "password": "clave-demo-2026"}, follow_redirects=True)
        self.assertIn("Sesión iniciada".encode(), response.data)

    def test_renderizado_de_paneles_y_formularios_segun_rol(self):
        customer = self.crear_cliente()
        worker = self.crear_trabajador()
        company = self.crear_empresa()
        admin = self.crear_administrador()
        project = self.crear_proyecto(company)
        application = Plataforma.postular(worker, project)
        self.plataforma.solicitar_oficio(worker, "Instalador de alarmas", "Instala alarmas de vivienda.")
        self.plataforma.crear_solicitud(customer, worker, "Revisar un tablero", self.oficio_id("Electricidad"), categorias=["hogar"])

        self.login(customer)
        self.assertEqual(self.client.get("/panel").status_code, 200)
        self.assertEqual(self.client.get(f"/trabajador/{worker.public_id}").status_code, 200)

        self.login(worker)
        for path in ("/panel", "/trabajador/perfil/editar", "/trabajador/oficios", "/proyectos", f"/proyectos/{project.id}"):
            with self.subTest(role="trabajador", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

        self.login(company, "clave-empresa-2026")
        for path in ("/empresa/panel", "/empresa/perfil", "/empresa/proyectos/nuevo", f"/empresa/proyectos/{project.id}/editar", f"/empresa/proyectos/{project.id}/postulaciones"):
            with self.subTest(role="empresa", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(application.estado, "pendiente")

        self.login(admin, "clave-admin-2026")
        for path in ("/academico", "/admin/oficios", "/admin/usuarios"):
            with self.subTest(role="administrador", path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        response = self.client.post("/academico/subcategoria", data={
            "padre_id": str(self.oficio_id("Construcción")), "nombre": "Domótica",
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(db.session.scalar(select(Oficio.id).where(Oficio.nombre == "Domótica")))
        response = self.client.post("/academico/deshacer", follow_redirects=True)
        self.assertIn("Acción deshecha".encode(), response.data)
        self.assertIsNone(db.session.scalar(select(Oficio.id).where(Oficio.nombre == "Domótica")))


class PersistenciaSQLiteTests(unittest.TestCase):
    """Simula reiniciar la app contra el mismo archivo SQLite temporal.

    La persistencia PostgreSQL real se verifica adicionalmente al ejecutar esta
    suite con TEST_DATABASE_URL apuntando a una base local terminada en _test.
    """
    def test_registro_permanece_al_crear_otra_instancia_de_app(self):
        instance_dir = Path(__file__).resolve().parent / "instance"
        instance_dir.mkdir(exist_ok=True)
        database_file = instance_dir / f"persistencia_test_{uuid4().hex}.db"
        uri = "sqlite:///" + database_file.as_posix()

        class FileTestConfig(IsolatedTestConfig):
            SQLALCHEMY_DATABASE_URI = uri

        try:
            first_app = create_app(FileTestConfig)
            with first_app.app_context():
                db.create_all()
                seed_referencias()
                usuario = first_app.extensions["oficiosya_plataforma"].registrar_cliente(
                    "Persistente", "Prueba", "persistente@example.test", "098600000", "clave-demo-2026",
                )
                public_id = usuario.public_id
                db.session.remove()
                db.engine.dispose()

            second_app = create_app(FileTestConfig)
            with second_app.app_context():
                recovered = db.session.scalar(select(Usuario).where(Usuario.public_id == public_id))
                self.assertIsNotNone(recovered)
                self.assertEqual(recovered.correo, "persistente@example.test")
                db.drop_all()
                db.session.remove()
                db.engine.dispose()
        finally:
            database_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
