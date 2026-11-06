"""Aplicación OficiosYa: Flask, PostgreSQL y estructuras de datos académicas."""
from __future__ import annotations

import os
from datetime import date
from functools import wraps

import click
from dotenv import load_dotenv
from flask import Flask, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

load_dotenv()

from config import Config, TestConfig
from extensions import csrf, db, login_manager, migrate
from db_models import (
    Usuario, Cliente, Trabajador, Empresa, Administrador, Oficio, Zona,
    SolicitudOficio, Proyecto, Postulacion, CategoriaServicio, Solicitud,
    Valoracion, zone_connections,
)
from modelos import Plataforma, ErrorDominio, seed_referencias


def role_required(*roles):
    """Protege la ruta en backend, no solo los enlaces de la plantilla."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles or not current_user.activo:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def plataforma_actual():
    return current_app.extensions["oficiosya_plataforma"]


def usuario_por_recurso(modelo, valor):
    return db.session.get(modelo, valor)


def _validar_zona(zona_id):
    if not zona_id:
        return None
    zona = db.session.get(Zona, zona_id)
    return zona if zona and zona.activa else None


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("Configura SECRET_KEY en .env antes de iniciar OficiosYa.")
    db.init_app(app)
    migrate.init_app(app, db, compare_type=True)
    login_manager.init_app(app)
    csrf.init_app(app)
    app.extensions["oficiosya_plataforma"] = Plataforma()

    @login_manager.user_loader
    def cargar_usuario(user_id):
        try:
            return db.session.get(Usuario, int(user_id))
        except (TypeError, ValueError):
            return None

    @app.before_request
    def cargar_indices_academicos():
        if request.endpoint != "static":
            try:
                plataforma_actual().reconstruir_indices()
            except Exception:
                db.session.rollback()
                # La página de diagnóstico y los comandos de migración deben poder
                # informar que aún falta inicializar el esquema.
                if request.endpoint not in ("health",):
                    raise

    @app.context_processor
    def contexto_global():
        try:
            oficinas = db.session.scalars(select(Oficio).where(Oficio.activo.is_(True)).order_by(Oficio.nombre)).all()
            zonas = db.session.scalars(select(Zona).where(Zona.activa.is_(True)).order_by(Zona.nombre)).all()
            categorias = db.session.scalars(select(CategoriaServicio).order_by(CategoriaServicio.id)).all()
        except Exception:
            db.session.rollback()
            oficinas, zonas, categorias = [], [], []
        return {
            "usuario_actual": current_user if current_user.is_authenticated else None,
            "oficios_catalogo": oficinas,
            "zonas_catalogo": zonas,
            "categorias_servicio": categorias,
            "arbol_filas": plataforma_actual().arbol.filas(),
        }

    @app.get("/health")
    def health():
        return {"app": "OficiosYa", "status": "ok"}

    @app.get("/")
    def inicio():
        oficio_id = request.args.get("oficio_id", type=int)
        zona = request.args.get("zona", "").strip()
        categoria = request.args.get("categoria", "").strip().lower()
        cercanas = request.args.get("cercanas", "1") == "1"
        if categoria not in ("", "hogar", "empresarial"):
            categoria = ""
        trabajadores = plataforma_actual().trabajadores_disponibles(oficio_id, zona, cercanas, categoria)
        filtros = {"oficio_id": oficio_id, "zona": zona, "categoria": categoria, "cercanas": cercanas}
        servicios = db.session.scalars(
            select(Solicitud).where(Solicitud.estado.in_(("pendiente", "en_proceso"))).order_by(Solicitud.creada_en.desc()).limit(30)
        ).all()
        if categoria:
            servicios = [s for s in servicios if categoria in {c.codigo for c in s.categorias}]
        if oficio_id:
            selected = db.session.get(Oficio, oficio_id)
            descendants = set(plataforma_actual().arbol.descendientes(selected.nombre)) if selected else set()
            servicios = [s for s in servicios if s.oficio.nombre in descendants]
        if zona:
            reachable = set(plataforma_actual().grafo.bfs(zona, 1 if cercanas else 0))
            servicios = [s for s in servicios if s.zona and s.zona.nombre in reachable]
        return render_template("index.html", trabajadores=trabajadores, filtros=filtros, servicios=servicios)

    @app.route("/registro", methods=["GET", "POST"])
    def registro():
        if request.method == "POST":
            try:
                rol = request.form.get("tipo", "cliente")
                nombre, apellido = request.form.get("nombre", ""), request.form.get("apellido", "")
                correo, telefono = request.form.get("correo", ""), request.form.get("telefono", "")
                password = request.form.get("password", "")
                plataforma = plataforma_actual()
                if rol == "cliente":
                    usuario = plataforma.registrar_cliente(nombre, apellido, correo, telefono, password)
                elif rol == "trabajador":
                    usuario = plataforma.registrar_trabajador(
                        nombre, apellido, correo, telefono, password,
                        request.form.getlist("oficios"), request.form.getlist("zonas"),
                        request.form.getlist("categorias"), request.form.get("descripcion", ""),
                        request.form.get("ubicacion", ""), request.form.get("experiencia", 0),
                    )
                elif rol == "empresa":
                    usuario = plataforma.registrar_empresa(
                        nombre, apellido, correo, telefono, password,
                        request.form.get("nombre_empresa", ""), request.form.get("ruc", ""),
                        request.form.get("direccion", ""), request.form.get("telefono_empresa", ""),
                        request.form.get("correo_empresa", ""), request.form.get("descripcion_empresa", ""),
                    )
                else:
                    raise ErrorDominio("Selecciona un tipo de cuenta permitido.")
                login_user(usuario)
                flash(f"Cuenta creada. Tu identificador es {usuario.public_id}.", "success")
                return redirect(url_for("panel" if rol != "empresa" else "panel_empresa"))
            except (ErrorDominio, ValueError) as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template("registro.html")

    @app.route("/acceso", methods=["GET", "POST"])
    def acceso():
        if request.method == "POST":
            login = (request.form.get("identificador") or request.form.get("correo") or "").strip()
            if "@" in login:
                usuario = db.session.scalar(select(Usuario).where(Usuario.correo == login.lower()))
            else:
                # Los identificadores públicos se resuelven por la tabla hash runtime.
                usuario = plataforma_actual().buscar_usuario(login)
            if usuario and usuario.activo and usuario.check_password(request.form.get("password", "")):
                login_user(usuario, remember=False)
                flash(f"Sesión iniciada como {usuario.nombre_completo}.", "success")
                return redirect(url_for("panel_empresa" if usuario.role == "empresa" else "panel"))
            flash("Correo o identificador y contraseña incorrectos, o cuenta desactivada.", "error")
        return render_template("acceso.html")

    @app.post("/salir")
    @login_required
    def salir():
        logout_user()
        flash("Sesión cerrada.", "info")
        return redirect(url_for("inicio"))

    @app.get("/trabajador/<identificador>")
    def perfil(identificador):
        trabajador = plataforma_actual().buscar_usuario(identificador)
        if not isinstance(trabajador, Trabajador) and identificador.isdecimal():
            trabajador = db.session.get(Trabajador, _int_or_none(identificador))
        if not trabajador:
            flash("No encontramos ese trabajador.", "error")
            return redirect(url_for("inicio"))
        return render_template("perfil.html", trabajador=trabajador)

    @app.post("/solicitudes/crear")
    @role_required("cliente")
    def crear_solicitud():
        try:
            trabajador = db.session.get(Trabajador, request.form.get("trabajador_id", type=int))
            if not trabajador:
                raise ErrorDominio("El trabajador seleccionado no existe.")
            zona = _validar_zona(request.form.get("zona_id", type=int))
            if request.form.get("zona_id") and not zona:
                raise ErrorDominio("Selecciona una zona válida.")
            solicitud = plataforma_actual().crear_solicitud(
                current_user, trabajador, request.form.get("descripcion", ""),
                request.form.get("oficio_id", type=int), zona.id if zona else None,
                request.form.getlist("categorias"), request.form.get("ubicacion", ""),
            )
            flash(f"Solicitud {solicitud.public_id} enviada a {trabajador.nombre_completo}.", "success")
            return redirect(url_for("panel"))
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("perfil", identificador=request.form.get("trabajador_id", "")))

    @app.get("/panel")
    @role_required("cliente", "trabajador")
    def panel():
        if current_user.role == "cliente":
            servicios = db.session.scalars(select(Solicitud).where(Solicitud.cliente_id == current_user.id).order_by(Solicitud.creada_en.desc())).all()
            return render_template("panel_cliente.html", usuario=current_user, solicitudes=servicios)
        solicitudes = db.session.scalars(select(Solicitud).where(Solicitud.trabajador_id == current_user.id).order_by(Solicitud.creada_en, Solicitud.id)).all()
        pendientes = [s for s in solicitudes if s.estado == "pendiente"]
        return render_template("panel_trabajador.html", usuario=current_user, solicitudes=solicitudes, pendientes=pendientes)

    @app.post("/solicitudes/<int:solicitud_id>/atender")
    @role_required("trabajador")
    def atender(solicitud_id):
        solicitud = db.session.get(Solicitud, solicitud_id)
        try:
            if not solicitud or solicitud.trabajador_id != current_user.id:
                raise ErrorDominio("La solicitud no pertenece a tu panel.")
            plataforma_actual().atender_siguiente(current_user, solicitud.public_id)
            flash(f"Atendiste {solicitud.public_id}, la solicitud pendiente más antigua.", "success")
        except ErrorDominio as exc:
            flash(str(exc), "error")
        return redirect(url_for("panel"))

    @app.post("/solicitudes/<int:solicitud_id>/estado")
    @role_required("trabajador")
    def actualizar_estado(solicitud_id):
        solicitud = db.session.get(Solicitud, solicitud_id)
        try:
            if not solicitud:
                raise ErrorDominio("La solicitud ya no existe.")
            plataforma_actual().cambiar_estado(solicitud, request.form.get("estado", ""), actor=current_user)
            flash(f"Estado de {solicitud.public_id} actualizado.", "success")
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("panel"))

    @app.post("/solicitudes/<int:solicitud_id>/valorar")
    @role_required("cliente")
    def valorar(solicitud_id):
        solicitud = db.session.get(Solicitud, solicitud_id)
        try:
            if not solicitud:
                raise ErrorDominio("El servicio no existe.")
            plataforma_actual().valorar(current_user, solicitud, request.form.get("puntuacion"), request.form.get("comentario", ""))
            flash("Gracias. Tu valoración fue registrada.", "success")
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("panel"))

    @app.route("/trabajador/perfil/editar", methods=["GET", "POST"])
    @role_required("trabajador")
    def editar_perfil_trabajador():
        if request.method == "POST":
            try:
                plataforma_actual().actualizar_perfil_trabajador(
                    current_user, request.form.get("descripcion", ""), request.form.get("ubicacion", ""),
                    request.form.get("experiencia", 0), request.form.getlist("oficios"),
                    request.form.getlist("zonas"), request.form.getlist("categorias"),
                )
                flash("Perfil profesional actualizado.", "success")
                return redirect(url_for("panel"))
            except ErrorDominio as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template("editar_trabajador.html", trabajador=current_user)

    @app.route("/trabajador/oficios", methods=["GET", "POST"])
    @role_required("trabajador")
    def solicitudes_oficios():
        if request.method == "POST":
            try:
                solicitud = plataforma_actual().solicitar_oficio(current_user, request.form.get("nombre", ""), request.form.get("descripcion", ""))
                flash(f"Solicitud de oficio enviada · estado {solicitud.estado}.", "success")
            except ErrorDominio as exc:
                db.session.rollback()
                flash(str(exc), "error")
            return redirect(url_for("solicitudes_oficios"))
        solicitudes = db.session.scalars(select(SolicitudOficio).where(SolicitudOficio.trabajador_id == current_user.id).order_by(SolicitudOficio.solicitada_en.desc())).all()
        return render_template("solicitudes_oficios.html", solicitudes=solicitudes)

    @app.get("/academico")
    @role_required("administrador")
    def academico():
        lista_proyectos = db.session.scalars(select(Proyecto).order_by(Proyecto.id)).unique().all()
        return render_template("academico.html", plataforma=plataforma_actual(), proyectos_academicos=lista_proyectos)

    @app.post("/academico/subcategoria")
    @role_required("administrador")
    def agregar_subcategoria():
        try:
            plataforma_actual().agregar_subcategoria(request.form.get("padre_id", type=int), request.form.get("nombre", ""), request.form.get("descripcion", ""), actor=current_user)
            flash("Oficio agregado al catálogo.", "success")
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("academico"))

    @app.post("/academico/deshacer")
    @role_required("administrador")
    def deshacer():
        try:
            accion = plataforma_actual().deshacer(current_user.id)
            flash(f"Acción deshecha: {accion}.", "success")
        except ErrorDominio as exc:
            flash(str(exc), "error")
        return redirect(url_for("academico"))

    @app.route("/admin/oficios", methods=["GET", "POST"])
    @role_required("administrador")
    def administrar_oficios():
        if request.method == "POST":
            solicitud = db.session.get(SolicitudOficio, request.form.get("solicitud_id", type=int))
            try:
                if not solicitud:
                    raise ErrorDominio("La solicitud de oficio no existe.")
                decision = request.form.get("decision", "")
                plataforma_actual().resolver_solicitud_oficio(solicitud, current_user, decision)
                flash(f"Solicitud {solicitud.id} {decision}.", "success")
            except ErrorDominio as exc:
                db.session.rollback()
                flash(str(exc), "error")
            return redirect(url_for("administrar_oficios"))
        solicitudes = db.session.scalars(select(SolicitudOficio).order_by(SolicitudOficio.solicitada_en.desc())).all()
        return render_template("admin_oficios.html", solicitudes=solicitudes)

    @app.route("/admin/usuarios", methods=["GET", "POST"])
    @role_required("administrador")
    def administrar_usuarios():
        if request.method == "POST":
            usuario = db.session.get(Usuario, request.form.get("usuario_id", type=int))
            try:
                if not usuario or usuario.id == current_user.id:
                    raise ErrorDominio("No puedes modificar esa cuenta.")
                usuario.activo = request.form.get("activo") == "1"
                db.session.commit()
                flash("Estado de la cuenta actualizado.", "success")
            except ErrorDominio as exc:
                db.session.rollback()
                flash(str(exc), "error")
            return redirect(url_for("administrar_usuarios"))
        usuarios = db.session.scalars(select(Usuario).order_by(Usuario.id)).unique().all()
        return render_template("admin_usuarios.html", usuarios=usuarios)

    @app.get("/empresas")
    def empresas():
        lista = db.session.scalars(select(Empresa).where(Empresa.activo.is_(True)).order_by(Empresa.nombre_empresa)).unique().all()
        return render_template("empresas.html", empresas=lista)

    @app.get("/proyectos")
    def proyectos():
        estado = request.args.get("estado", "abierto")
        query = select(Proyecto).order_by(Proyecto.inicio_estimado, Proyecto.id)
        if estado in Plataforma.ESTADOS_PROYECTO:
            query = query.where(Proyecto.estado == estado)
        lista = db.session.scalars(query).unique().all()
        return render_template("proyectos.html", proyectos=lista, estado=estado)

    @app.get("/proyectos/<int:project_id>")
    def detalle_proyecto(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        if not proyecto:
            abort(404)
        return render_template("proyecto_detalle.html", proyecto=proyecto)

    @app.post("/proyectos/<int:project_id>/postular")
    @role_required("trabajador")
    def postularse(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        try:
            if not proyecto:
                raise ErrorDominio("El proyecto no existe.")
            Plataforma.postular(current_user, proyecto)
            flash("Postulación enviada.", "success")
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("detalle_proyecto", project_id=project_id))

    @app.get("/empresa/panel")
    @role_required("empresa")
    def panel_empresa():
        return render_template("panel_empresa.html", empresa=current_user, proyectos=current_user.proyectos)

    @app.route("/empresa/perfil", methods=["GET", "POST"])
    @role_required("empresa")
    def perfil_empresa():
        if request.method == "POST":
            try:
                plataforma_actual().actualizar_perfil_empresa(current_user, request.form.get("nombre_empresa", ""), request.form.get("ruc", ""), request.form.get("direccion", ""), request.form.get("telefono_empresa", ""), request.form.get("correo_empresa", ""), request.form.get("descripcion", ""))
                flash("Perfil empresarial actualizado.", "success")
                return redirect(url_for("panel_empresa"))
            except ErrorDominio as exc:
                db.session.rollback()
                flash(str(exc), "error")
        return render_template("perfil_empresa.html", empresa=current_user)

    @app.route("/empresa/proyectos/nuevo", methods=["GET", "POST"])
    @role_required("empresa")
    def nuevo_proyecto():
        if request.method == "POST":
            try:
                datos = _datos_proyecto(request.form)
                proyecto = Plataforma.crear_proyecto(current_user, datos, request.form.getlist("oficios"))
                flash("Proyecto publicado.", "success")
                return redirect(url_for("detalle_proyecto", project_id=proyecto.id))
            except (ErrorDominio, ValueError) as exc:
                db.session.rollback()
                flash(str(exc) or "Revisa las fechas y cantidades del proyecto.", "error")
        return render_template("form_proyecto.html", proyecto=None)

    @app.route("/empresa/proyectos/<int:project_id>/editar", methods=["GET", "POST"])
    @role_required("empresa")
    def editar_proyecto(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        if not proyecto:
            abort(404)
        if proyecto.empresa_id != current_user.id:
            abort(403)
        if request.method == "POST":
            try:
                datos = _datos_proyecto(request.form, estado=proyecto.estado)
                Plataforma.actualizar_proyecto(current_user, proyecto, datos, request.form.getlist("oficios"))
                flash("Proyecto actualizado.", "success")
                return redirect(url_for("panel_empresa"))
            except (ErrorDominio, ValueError) as exc:
                db.session.rollback()
                flash(str(exc) or "Revisa los datos del proyecto.", "error")
        return render_template("form_proyecto.html", proyecto=proyecto)

    @app.post("/empresa/proyectos/<int:project_id>/eliminar")
    @role_required("empresa")
    def eliminar_proyecto(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        if not proyecto:
            abort(404)
        if proyecto.empresa_id != current_user.id:
            abort(403)
        if proyecto.estado != "abierto" or any(p.estado == "aceptada" for p in proyecto.postulaciones):
            flash("Solo se eliminan proyectos abiertos sin postulaciones aceptadas.", "error")
        else:
            db.session.delete(proyecto)
            db.session.commit()
            flash("Proyecto eliminado.", "success")
        return redirect(url_for("panel_empresa"))

    @app.post("/empresa/proyectos/<int:project_id>/estado")
    @role_required("empresa")
    def estado_proyecto(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        if not proyecto:
            abort(404)
        if proyecto.empresa_id != current_user.id:
            abort(403)
        estado = request.form.get("estado", "")
        if estado not in Plataforma.ESTADOS_PROYECTO:
            flash("Estado de proyecto inválido.", "error")
        else:
            proyecto.estado = estado
            db.session.commit()
            flash("Estado de proyecto actualizado.", "success")
        return redirect(url_for("panel_empresa"))

    @app.get("/empresa/proyectos/<int:project_id>/postulaciones")
    @role_required("empresa")
    def postulaciones_recibidas(project_id):
        proyecto = db.session.get(Proyecto, project_id)
        if not proyecto:
            abort(404)
        if proyecto.empresa_id != current_user.id:
            abort(403)
        return render_template("postulaciones.html", proyecto=proyecto, postulaciones=proyecto.postulaciones)

    @app.post("/empresa/postulaciones/<int:application_id>/resolver")
    @role_required("empresa")
    def resolver_postulacion(application_id):
        postulacion = db.session.get(Postulacion, application_id)
        try:
            if not postulacion:
                raise ErrorDominio("La postulación no existe.")
            Plataforma.resolver_postulacion(current_user, postulacion, request.form.get("estado", ""))
            flash("Decisión de postulación guardada.", "success")
        except ErrorDominio as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("postulaciones_recibidas", project_id=postulacion.proyecto_id))

    @app.cli.command("seed-references")
    def seed_references_command():
        """Carga categorías, zonas y las dos categorías de servicios."""
        seed_referencias()
        click.echo("Catálogo y zonas inicializados.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Crea un administrador local; no hay registro público de administradores."""
        nombre = click.prompt("Nombre")
        apellido = click.prompt("Apellido")
        correo = click.prompt("Correo electrónico").strip().lower()
        telefono = click.prompt("Teléfono")
        password = click.prompt("Contraseña (mínimo 10 caracteres)", hide_input=True, confirmation_prompt=True)
        try:
            admin = plataforma_actual()._crear_usuario(Administrador, "ADM", nombre, apellido, correo, telefono, password)
            click.echo(f"Administrador creado: {admin.public_id}")
        except ErrorDominio as exc:
            raise click.ClickException(str(exc))

    @app.cli.command("seed-demo")
    @click.option("--password", envvar="DEMO_PASSWORD", prompt=True, hide_input=True, confirmation_prompt=True)
    def seed_demo_command(password):
        """Carga usuarios/proyectos ficticios para la exposición (no se ejecuta al iniciar)."""
        if not app.config.get("TESTING") and app.config["SQLALCHEMY_DATABASE_URI"].endswith("oficiosya"):
            if not click.confirm("Vas a añadir cuentas ficticias a la base oficiosya. ¿Continuar?"):
                raise click.Abort()
        seed_referencias()
        if db.session.scalar(select(Usuario.id).limit(1)):
            click.echo("La base ya contiene usuarios; seed-demo no hizo cambios.")
            return
        oficinas = {o.nombre: o for o in db.session.scalars(select(Oficio)).all()}
        zonas = {z.nombre: z for z in db.session.scalars(select(Zona)).all()}
        def new_user(cls, prefix, first, last, email, phone):
            user = cls(nombre=first, apellido=last, correo=email, telefono=phone, activo=True)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            user.public_id = f"{prefix}-{user.id:06d}"
            return user
        try:
            c1 = new_user(Cliente, "CLI", "Valeria", "Benítez", "valeria.demo@oficiosya.test", "0981 555 101")
            c2 = new_user(Cliente, "CLI", "Mateo", "Rojas", "mateo.demo@oficiosya.test", "0982 555 202")
            workers = [
                ("Luz", "Acosta", "luz.demo@oficiosya.test", "Electricidad", ["Asunción", "Lambaré"]),
                ("Diego", "Ferreira", "diego.demo@oficiosya.test", "Plomería", ["San Lorenzo", "Capiatá"]),
                ("Noelia", "Duarte", "noelia.demo@oficiosya.test", "Carpintería", ["Luque"]),
                ("Bruno", "Vera", "bruno.demo@oficiosya.test", "Pintura", ["Fernando de la Mora", "Asunción"]),
                ("Camila", "Ortiz", "camila.demo@oficiosya.test", "Aire acondicionado", ["Mariano Roque Alonso"]),
            ]
            created = []
            for first, last, email, trade, coverage in workers:
                worker = new_user(Trabajador, "TRA", first, last, email, "0983 555 000")
                worker.oficios = [oficinas[trade]]
                worker.zonas = [zonas[z] for z in coverage]
                worker.categorias_servicio = db.session.scalars(select(CategoriaServicio)).all()
                created.append(worker)
            db.session.flush()
            servicio1 = Solicitud(public_id="SRV-DEMO-001", cliente=c1, trabajador=created[0], oficio=oficinas["Electricidad"], zona=zonas["Asunción"], descripcion="Revisar una instalación eléctrica", ubicacion="Asunción", estado="pendiente", categorias=db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo == "hogar")).all())
            servicio2 = Solicitud(public_id="SRV-DEMO-002", cliente=c2, trabajador=created[0], oficio=oficinas["Electricidad"], zona=zonas["Asunción"], descripcion="Instalar una lámpara", ubicacion="Asunción", estado="pendiente", categorias=db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo == "hogar")).all())
            servicio3 = Solicitud(public_id="SRV-DEMO-003", cliente=c2, trabajador=created[1], oficio=oficinas["Plomería"], zona=zonas["San Lorenzo"], descripcion="Revisar una canilla", ubicacion="San Lorenzo", estado="finalizada", categorias=db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo == "hogar")).all())
            db.session.add_all([servicio1, servicio2, servicio3])
            db.session.flush()
            db.session.add(Valoracion(servicio=servicio3, cliente_id=c2.id, trabajador_id=created[1].id, puntuacion=5, comentario="Trabajo prolijo y puntual"))
            company = Empresa(nombre="Equipo", apellido="Demo", correo="empresa.demo@oficiosya.test", telefono="021 555 000", activo=True, nombre_empresa="Constructora Demostración", ruc="80000000-1", direccion="Asunción", telefono_empresa="021 555 010", correo_empresa="empresa@oficiosya.test", descripcion="Empresa ficticia para la demostración académica.")
            company.set_password(password)
            db.session.add(company)
            db.session.flush()
            company.public_id = f"EMP-{company.id:06d}"
            db.session.flush()
            proyecto = Proyecto(empresa=company, nombre="Adecuación de local", descripcion="Reparaciones y pintura de local comercial.", trabajadores_necesarios=3, ubicacion="Asunción", inicio_estimado=date.today(), duracion_dias=14, presupuesto=None, estado="abierto", oficios=[oficinas["Pintura"], oficinas["Electricidad"]])
            db.session.add(proyecto)
            db.session.commit()
            click.echo("Datos demo cargados. Usa la contraseña introducida para todos los perfiles demo.")
        except Exception:
            db.session.rollback()
            raise

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template("error.html", titulo="Formulario vencido", mensaje="Recarga la página y vuelve a enviar el formulario."), 400

    @app.errorhandler(OperationalError)
    def base_no_disponible(_error):
        db.session.rollback()
        return render_template("error.html", titulo="Base de datos no disponible", mensaje="Comprueba que PostgreSQL esté iniciado y que DATABASE_URL en .env tenga usuario, contraseña, puerto y base de datos correctos."), 503

    @app.errorhandler(403)
    def no_autorizado(_error):
        return render_template("error.html", titulo="Acceso no permitido", mensaje="Tu cuenta no tiene permiso para esta operación."), 403

    @app.errorhandler(404)
    def no_encontrado(_error):
        return render_template("404.html"), 404

    return app


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _datos_proyecto(form, estado="abierto"):
    try:
        inicio = date.fromisoformat(form.get("inicio_estimado", ""))
        trabajadores = int(form.get("trabajadores_necesarios", "0"))
        duracion = int(form.get("duracion_dias", "0"))
        presupuesto_raw = form.get("presupuesto", "").strip()
        presupuesto = float(presupuesto_raw) if presupuesto_raw else None
    except (TypeError, ValueError):
        raise ErrorDominio("Revisa fecha, cantidad de trabajadores, duración y presupuesto.")
    if trabajadores < 1 or duracion < 1 or (presupuesto is not None and presupuesto < 0):
        raise ErrorDominio("La cantidad y duración deben ser mayores que cero; presupuesto no puede ser negativo.")
    return {
        "nombre": form.get("nombre", "").strip(),
        "descripcion": form.get("descripcion", "").strip(),
        "trabajadores_necesarios": trabajadores,
        "ubicacion": form.get("ubicacion", "").strip(),
        "inicio_estimado": inicio,
        "duracion_dias": duracion,
        "presupuesto": presupuesto,
        "estado": estado,
    }


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1")
