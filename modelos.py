"""Servicios de dominio y adaptador de las estructuras académicas a PostgreSQL."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from extensions import db
from db_models import (
    Usuario, Cliente, Trabajador, Empresa, Administrador, Oficio, Zona,
    SolicitudOficio, Proyecto, Postulacion, CategoriaServicio, Solicitud,
    Valoracion, zone_connections,
)
from estructuras import ListaEnlazada, ColaFIFO, PilaLIFO, AccionReversible, ArbolOficios, GrafoZonas, TablaHash


class ErrorDominio(ValueError):
    """Error de validación que puede presentarse directamente al usuario."""


def normalizar_nombre(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", (valor or "").casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


class Plataforma:
    """Coordina transacciones SQL y mantiene índices académicos reconstruibles.

    PostgreSQL es la fuente duradera. Las listas, colas, árbol, grafo y hash
    son vistas de ejecución usadas por la lógica y por el panel académico.
    """
    ESTADOS_SERVICIO = ("pendiente", "en_proceso", "finalizada", "cancelada")
    ESTADOS_PROYECTO = ("abierto", "en_proceso", "finalizado")

    def __init__(self):
        self.clientes = ListaEnlazada()
        self.trabajadores = ListaEnlazada()
        self.solicitudes = ListaEnlazada()
        self.usuarios = TablaHash()
        self.arbol = ArbolOficios()
        self.grafo = GrafoZonas()
        self.historial = PilaLIFO()

    def reconstruir_indices(self):
        """Recarga estructuras desde SQL sin borrar la pila de esta ejecución."""
        self.clientes = ListaEnlazada()
        self.trabajadores = ListaEnlazada()
        self.solicitudes = ListaEnlazada()
        self.usuarios = TablaHash()
        for usuario in db.session.scalars(select(Usuario).order_by(Usuario.id)).unique():
            if usuario.public_id:
                self.usuarios.insertar(usuario.public_id, usuario)
            if isinstance(usuario, Cliente):
                self.clientes.agregar(usuario)
            elif isinstance(usuario, Trabajador):
                usuario._cola_pendientes = ColaFIFO()
                self.trabajadores.agregar(usuario)
        for solicitud in db.session.scalars(select(Solicitud).order_by(Solicitud.creada_en, Solicitud.id)).unique():
            self.solicitudes.agregar(solicitud)
        por_id = {t.id: t for t in self.trabajadores}
        for solicitud in self.solicitudes:
            if solicitud.estado == "pendiente" and solicitud.trabajador_id in por_id:
                por_id[solicitud.trabajador_id]._cola_pendientes.encolar(solicitud)

        self.arbol = ArbolOficios("Oficios")
        offices = db.session.scalars(select(Oficio).where(Oficio.activo.is_(True)).order_by(Oficio.id)).all()
        names = {o.id: o.nombre for o in offices}
        for office in offices:
            if office.parent_id is None and office.nombre.casefold() != "oficios":
                self.arbol.agregar("Oficios", office.nombre)
        for office in offices:
            if office.parent_id is not None and office.parent_id in names:
                self.arbol.agregar(names[office.parent_id], office.nombre)

        self.grafo = GrafoZonas()
        zones = db.session.scalars(select(Zona).where(Zona.activa.is_(True))).all()
        by_zone = {z.id: z.nombre for z in zones}
        for zone in zones:
            self.grafo.agregar_zona(zone.nombre)
        for a_id, b_id in db.session.execute(select(zone_connections.c.zone_a_id, zone_connections.c.zone_b_id)):
            if a_id in by_zone and b_id in by_zone:
                self.grafo.conectar(by_zone[a_id], by_zone[b_id])

    @staticmethod
    def validar_nombre_apellido(nombre, apellido):
        if not nombre or not nombre.strip() or not apellido or not apellido.strip():
            raise ErrorDominio("Completa nombre y apellido.")

    @staticmethod
    def validar_contacto(correo, telefono):
        if not correo or "@" not in correo or "." not in correo.rsplit("@", 1)[-1]:
            raise ErrorDominio("Escribe un correo electrónico válido.")
        if not telefono or not telefono.strip():
            raise ErrorDominio("Completa el teléfono.")
        if db.session.scalar(select(Usuario.id).where(func.lower(Usuario.correo) == correo.strip().lower())):
            raise ErrorDominio("Ya existe una cuenta con ese correo.")

    @staticmethod
    def validar_password(password):
        if not password or len(password) < 10:
            raise ErrorDominio("La contraseña debe tener al menos 10 caracteres.")

    @staticmethod
    def _ids_validos(valores, etiqueta):
        try:
            ids = [int(v) for v in valores]
        except (TypeError, ValueError):
            raise ErrorDominio(f"Hay un identificador inválido en {etiqueta}.")
        if any(v <= 0 for v in ids):
            raise ErrorDominio(f"Hay un identificador inválido en {etiqueta}.")
        return ids

    def _crear_usuario(self, clase, prefijo, nombre, apellido, correo, telefono, password):
        self.validar_nombre_apellido(nombre, apellido)
        self.validar_contacto(correo, telefono)
        self.validar_password(password)
        usuario = clase(nombre=nombre.strip(), apellido=apellido.strip(), correo=correo.strip().lower(), telefono=telefono.strip(), activo=True)
        usuario.set_password(password)
        db.session.add(usuario)
        try:
            db.session.flush()
            usuario.public_id = f"{prefijo}-{usuario.id:06d}"
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("No se pudo crear la cuenta: el correo o identificador ya existe.")
        self.reconstruir_indices()
        return usuario

    def registrar_cliente(self, nombre, apellido, correo, telefono, password):
        return self._crear_usuario(Cliente, "CLI", nombre, apellido, correo, telefono, password)

    def registrar_trabajador(self, nombre, apellido, correo, telefono, password, oficios, zonas, categorias, descripcion="", ubicacion="", experiencia=0):
        self.validar_nombre_apellido(nombre, apellido)
        self.validar_contacto(correo, telefono)
        self.validar_password(password)
        oficios = self._ids_validos(oficios, "oficios")
        zonas = self._ids_validos(zonas, "zonas")
        if not oficios:
            raise ErrorDominio("Selecciona al menos un oficio aprobado.")
        if not zonas:
            raise ErrorDominio("Selecciona al menos una zona de cobertura.")
        if len(set(oficios)) != len(oficios):
            raise ErrorDominio("No repitas oficios en el perfil.")
        lista_oficios = db.session.scalars(select(Oficio).where(Oficio.id.in_(oficios), Oficio.activo.is_(True))).all()
        lista_zonas = db.session.scalars(select(Zona).where(Zona.id.in_(zonas), Zona.activa.is_(True))).all()
        categorias = list(dict.fromkeys(categorias or []))
        lista_categorias = db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo.in_(categorias))).all()
        if not lista_categorias or len(lista_categorias) != len(categorias):
            raise ErrorDominio("Selecciona Hogar, Empresarial o ambas categorías.")
        if len(lista_oficios) != len(set(oficios)):
            raise ErrorDominio("Uno de los oficios seleccionados no está aprobado o disponible.")
        if len(lista_zonas) != len(set(zonas)):
            raise ErrorDominio("Una de las zonas seleccionadas no está disponible.")
        self._validar_experiencia(experiencia)
        trabajador = Trabajador(nombre=nombre.strip(), apellido=apellido.strip(), correo=correo.strip().lower(), telefono=telefono.strip(), activo=True, descripcion_profesional=(descripcion or "").strip(), ubicacion=(ubicacion or "").strip(), experiencia_anios=int(experiencia or 0), oficios=lista_oficios, zonas=lista_zonas, categorias_servicio=lista_categorias)
        trabajador.set_password(password)
        db.session.add(trabajador)
        try:
            db.session.flush()
            trabajador.public_id = f"TRA-{trabajador.id:06d}"
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("No se pudo crear el perfil de trabajador.")
        self.reconstruir_indices()
        return trabajador

    def registrar_empresa(self, nombre, apellido, correo, telefono, password, nombre_empresa, ruc, direccion, telefono_empresa, correo_empresa, descripcion):
        if not all(v and str(v).strip() for v in (nombre_empresa, ruc, direccion, telefono_empresa, correo_empresa)):
            raise ErrorDominio("Completa los datos obligatorios de la empresa.")
        if db.session.scalar(select(Empresa.id).where(Empresa.ruc == ruc.strip())):
            raise ErrorDominio("Ya existe una empresa con ese RUC.")
        empresa = Empresa(nombre=nombre.strip(), apellido=apellido.strip(), correo=correo.strip().lower(), telefono=telefono.strip(), activo=True, nombre_empresa=nombre_empresa.strip(), ruc=ruc.strip(), direccion=direccion.strip(), telefono_empresa=telefono_empresa.strip(), correo_empresa=correo_empresa.strip().lower(), descripcion=(descripcion or "").strip())
        self.validar_nombre_apellido(nombre, apellido)
        self.validar_contacto(correo, telefono)
        self.validar_password(password)
        empresa.set_password(password)
        db.session.add(empresa)
        try:
            db.session.flush()
            empresa.public_id = f"EMP-{empresa.id:06d}"
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("No se pudo crear la cuenta empresarial; revisa correo y RUC.")
        self.reconstruir_indices()
        return empresa

    @staticmethod
    def _validar_experiencia(valor):
        try:
            if int(valor or 0) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise ErrorDominio("La experiencia debe ser un número entero igual o mayor que cero.")

    def buscar_usuario(self, identificador):
        if not identificador:
            return None
        encontrado = self.usuarios.buscar(identificador.strip().upper())
        if encontrado:
            return encontrado
        return db.session.scalar(select(Usuario).where(func.lower(Usuario.correo) == identificador.strip().lower()))

    def actualizar_oficios(self, trabajador, oficio_ids):
        oficio_ids = self._ids_validos(oficio_ids, "oficios")
        oficio_ids = list(dict.fromkeys(oficio_ids))
        if not oficio_ids:
            raise ErrorDominio("Un trabajador debe conservar al menos un oficio aprobado.")
        oficios = db.session.scalars(select(Oficio).where(Oficio.id.in_(oficio_ids), Oficio.activo.is_(True))).all()
        if len(oficios) != len(oficio_ids):
            raise ErrorDominio("Solo puedes asociar oficios aprobados.")
        trabajador.oficios = oficios
        db.session.commit()
        self.reconstruir_indices()

    def actualizar_perfil_trabajador(self, trabajador, descripcion, ubicacion, experiencia, oficio_ids, zona_ids, categorias):
        zona_ids = self._ids_validos(zona_ids, "zonas")
        self._validar_experiencia(experiencia)
        zonas = db.session.scalars(select(Zona).where(Zona.id.in_(list(dict.fromkeys(zona_ids))), Zona.activa.is_(True))).all()
        if not zonas:
            raise ErrorDominio("Selecciona al menos una zona de cobertura.")
        trabajador.descripcion_profesional = (descripcion or "").strip()
        trabajador.ubicacion = (ubicacion or "").strip()
        trabajador.experiencia_anios = int(experiencia or 0)
        trabajador.zonas = zonas
        categorias = list(dict.fromkeys(categorias or []))
        trabajador.categorias_servicio = db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo.in_(categorias))).all()
        if not trabajador.categorias_servicio:
            raise ErrorDominio("Selecciona al menos una categoría de servicio.")
        self.actualizar_oficios(trabajador, oficio_ids)

    def actualizar_perfil_empresa(self, empresa, nombre_empresa, ruc, direccion, telefono_empresa, correo_empresa, descripcion):
        if not all(v and str(v).strip() for v in (nombre_empresa, ruc, direccion, telefono_empresa, correo_empresa)):
            raise ErrorDominio("Completa los datos obligatorios de la empresa.")
        conflicto = db.session.scalar(select(Empresa.id).where(Empresa.ruc == ruc.strip(), Empresa.id != empresa.id))
        if conflicto:
            raise ErrorDominio("Ese RUC ya pertenece a otra empresa.")
        empresa.nombre_empresa = nombre_empresa.strip()
        empresa.ruc = ruc.strip()
        empresa.direccion = direccion.strip()
        empresa.telefono_empresa = telefono_empresa.strip()
        empresa.correo_empresa = correo_empresa.strip().lower()
        empresa.descripcion = (descripcion or "").strip()
        db.session.commit()

    def trabajadores_disponibles(self, oficio_id=None, zona_nombre="", incluir_vecinas=True, categoria=""):
        distancias = self.grafo.bfs(zona_nombre, 1 if incluir_vecinas else 0) if zona_nombre else {}
        oficina_obj = db.session.get(Oficio, oficio_id) if oficio_id else None
        if oficio_id and not oficina_obj:
            return []
        nombres_oficio = set(self.arbol.descendientes(oficina_obj.nombre)) if oficina_obj and oficina_obj.activo else set()
        resultados = []
        for trabajador in self.trabajadores:
            if not trabajador.activo:
                continue
            if nombres_oficio and not any(o.nombre in nombres_oficio for o in trabajador.oficios):
                continue
            if oficina_obj and not nombres_oficio:
                continue
            worker_zones = [z.nombre for z in trabajador.zonas if z.activa]
            zona_match = next((z for z in worker_zones if not zona_nombre or z in distancias), None)
            if zona_nombre and not zona_match:
                continue
            if categoria and categoria not in {c.codigo for c in trabajador.categorias_servicio}:
                continue
            distancia = distancias.get(zona_match, 0) if zona_nombre and zona_match else 0
            resultados.append((trabajador, distancia, zona_match or (worker_zones[0] if worker_zones else "Sin zona")))
        return resultados

    def crear_solicitud(self, cliente, trabajador, descripcion, oficio_id=None, zona_id=None, categorias=None, ubicacion=""):
        if not isinstance(cliente, Cliente):
            raise ErrorDominio("Inicia sesión como cliente para solicitar un servicio.")
        if not isinstance(trabajador, Trabajador) or not trabajador.activo:
            raise ErrorDominio("El trabajador seleccionado no está disponible.")
        if not descripcion or not descripcion.strip():
            raise ErrorDominio("Describe brevemente el trabajo solicitado.")
        if len(descripcion.strip()) > 3000 or len((ubicacion or "").strip()) > 240:
            raise ErrorDominio("La descripción admite hasta 3000 caracteres y la ubicación hasta 240.")
        if oficio_id is not None:
            try:
                oficio_id = int(oficio_id)
            except (TypeError, ValueError):
                raise ErrorDominio("Selecciona un oficio válido.")
        oficios_permitidos = {o.id for o in trabajador.oficios if o.activo}
        if oficio_id is None:
            oficio_id = next(iter(oficios_permitidos), None)
        if oficio_id not in oficios_permitidos:
            raise ErrorDominio("El trabajador no tiene asociado el oficio seleccionado.")
        if zona_id is not None:
            try:
                zona_id = int(zona_id)
            except (TypeError, ValueError):
                raise ErrorDominio("Selecciona una zona válida.")
            if zona_id not in {z.id for z in trabajador.zonas if z.activa}:
                raise ErrorDominio("Selecciona una zona de cobertura del trabajador.")
        lista_categorias = list(dict.fromkeys(categorias or ["hogar"]))
        if not lista_categorias or any(c not in {"hogar", "empresarial"} for c in lista_categorias):
            raise ErrorDominio("Selecciona Hogar, Empresarial o ambas categorías.")
        permitidas = {categoria.codigo for categoria in trabajador.categorias_servicio}
        if not set(lista_categorias).issubset(permitidas):
            raise ErrorDominio("El trabajador no ofrece una de las categorías seleccionadas.")
        categorias_db = db.session.scalars(select(CategoriaServicio).where(CategoriaServicio.codigo.in_(lista_categorias))).all()
        if len(categorias_db) != len(lista_categorias):
            raise ErrorDominio("Las categorías de servicio aún no están inicializadas.")
        solicitud = Solicitud(cliente=cliente, trabajador=trabajador, descripcion=descripcion.strip(), oficio_id=oficio_id, zona_id=zona_id, ubicacion=(ubicacion or "").strip(), categorias=categorias_db, estado="pendiente", public_id="pendiente")
        db.session.add(solicitud)
        try:
            db.session.flush()
            solicitud.public_id = f"SRV-{solicitud.id:06d}"
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("No se pudo registrar la solicitud.")
        self.historial.apilar(AccionReversible(f"Solicitud {solicitud.public_id}", lambda: self._deshacer_solicitud(solicitud.id), cliente.id))
        self.reconstruir_indices()
        return solicitud

    def _deshacer_solicitud(self, solicitud_id):
        solicitud = db.session.get(Solicitud, solicitud_id)
        if not solicitud or solicitud.estado != "pendiente":
            return False
        cola = getattr(solicitud.trabajador, "_cola_pendientes", None)
        if cola and cola.primero() is not solicitud:
            return False
        db.session.delete(solicitud)
        db.session.commit()
        self.reconstruir_indices()
        return True

    def atender_siguiente(self, trabajador, identificador=None):
        cola = getattr(trabajador, "_cola_pendientes", ColaFIFO())
        solicitud = cola.primero()
        if not solicitud:
            raise ErrorDominio("No tienes solicitudes pendientes.")
        if identificador and solicitud.public_id != identificador:
            raise ErrorDominio(f"La siguiente solicitud FIFO es {solicitud.public_id}; atiéndela antes.")
        solicitud.estado = "en_proceso"
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise ErrorDominio("No se pudo actualizar la solicitud en la base de datos.")
        cola.desencolar()
        self.historial.apilar(AccionReversible(f"Atención de {solicitud.public_id}", lambda: self._revertir_atencion(solicitud.id), trabajador.id))
        return solicitud

    def _revertir_atencion(self, solicitud_id):
        solicitud = db.session.get(Solicitud, solicitud_id)
        if not solicitud or solicitud.estado != "en_proceso":
            return False
        solicitud.estado = "pendiente"
        db.session.commit()
        self.reconstruir_indices()
        return True

    def cambiar_estado(self, solicitud, nuevo_estado, actor=None):
        if nuevo_estado not in self.ESTADOS_SERVICIO:
            raise ErrorDominio("Estado de servicio no reconocido.")
        if actor is not solicitud.trabajador:
            raise ErrorDominio("Solo el trabajador asignado puede actualizar este servicio.")
        if solicitud.estado != "en_proceso":
            raise ErrorDominio("Atiende primero la siguiente solicitud de la cola FIFO.")
        if nuevo_estado not in ("finalizada", "cancelada"):
            raise ErrorDominio("Desde En proceso, el estado permitido es Finalizada o Cancelada.")
        anterior = solicitud.estado
        solicitud.estado = nuevo_estado
        db.session.commit()
        self.historial.apilar(AccionReversible(f"Estado de {solicitud.public_id}: {nuevo_estado}", lambda: self._revertir_estado(solicitud.id, anterior, nuevo_estado), actor.id))

    def _revertir_estado(self, solicitud_id, anterior, esperado):
        solicitud = db.session.get(Solicitud, solicitud_id)
        if not solicitud or solicitud.estado != esperado or solicitud.valoracion:
            return False
        solicitud.estado = anterior
        db.session.commit()
        self.reconstruir_indices()
        return True

    def valorar(self, cliente, solicitud, puntuacion, comentario=""):
        if solicitud.cliente_id != cliente.id:
            raise ErrorDominio("Solo el cliente que solicitó el servicio puede valorarlo.")
        if solicitud.estado != "finalizada":
            raise ErrorDominio("Solo puedes valorar un trabajo finalizado.")
        if solicitud.valoracion:
            raise ErrorDominio("Este servicio ya tiene una valoración.")
        try:
            puntuacion = int(puntuacion)
        except (TypeError, ValueError):
            raise ErrorDominio("La puntuación debe ser un número de 1 a 5.")
        if puntuacion not in range(1, 6):
            raise ErrorDominio("La puntuación debe ser de 1 a 5.")
        valoracion = Valoracion(servicio=solicitud, cliente_id=cliente.id, trabajador_id=solicitud.trabajador_id, puntuacion=puntuacion, comentario=(comentario or "").strip()[:1000])
        db.session.add(valoracion)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("Este servicio ya tiene una valoración.")
        self.historial.apilar(AccionReversible(f"Valoración de {solicitud.public_id}", lambda: self._deshacer_valoracion(valoracion.id), cliente.id))
        return valoracion

    def _deshacer_valoracion(self, valoracion_id):
        valoracion = db.session.get(Valoracion, valoracion_id)
        if not valoracion:
            return False
        db.session.delete(valoracion)
        db.session.commit()
        return True

    def agregar_subcategoria(self, padre_id, nombre, descripcion="", actor=None):
        nombre = (nombre or "").strip()
        if not nombre or len(nombre) > 120:
            raise ErrorDominio("El nombre del oficio debe tener entre 1 y 120 caracteres.")
        clave = normalizar_nombre(nombre)
        existentes = db.session.scalars(select(Oficio).where(Oficio.activo.is_(True))).all()
        pendientes = db.session.scalars(select(SolicitudOficio).where(SolicitudOficio.estado == "pendiente")).all()
        for otro in [o.nombre for o in existentes] + [r.nombre_propuesto for r in pendientes]:
            similitud = SequenceMatcher(None, clave, normalizar_nombre(otro)).ratio()
            if clave == normalizar_nombre(otro) or similitud >= 0.88:
                raise ErrorDominio(f"Ya existe un oficio o propuesta similar: {otro}.")
        try:
            padre_id = int(padre_id)
        except (TypeError, ValueError):
            raise ErrorDominio("Selecciona una categoría padre válida.")
        padre = db.session.get(Oficio, padre_id)
        if not padre or not padre.activo:
            raise ErrorDominio("Selecciona una categoría padre válida.")
        office = Oficio(nombre=nombre, nombre_normalizado=clave, descripcion=(descripcion or "").strip(), padre=padre, activo=True)
        db.session.add(office)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("Ese oficio ya existe.")
        self.historial.apilar(AccionReversible(f"Subcategoría {nombre}", lambda: self._deshacer_subcategoria(office.id), getattr(actor, "id", None)))
        self.reconstruir_indices()
        return office

    def _deshacer_subcategoria(self, office_id):
        office = db.session.get(Oficio, office_id)
        if not office or office.hijos or office.trabajadores:
            return False
        db.session.delete(office)
        db.session.commit()
        self.reconstruir_indices()
        return True

    def solicitar_oficio(self, trabajador, nombre, descripcion):
        nombre = (nombre or "").strip()
        descripcion = (descripcion or "").strip()
        if not nombre or not descripcion:
            raise ErrorDominio("Escribe el nombre y la descripción del oficio propuesto.")
        if len(nombre) > 120 or len(descripcion) > 3000:
            raise ErrorDominio("El oficio admite hasta 120 caracteres y la descripción hasta 3000.")
        clave = normalizar_nombre(nombre)
        lista_catalogo = db.session.scalars(select(Oficio).where(Oficio.activo.is_(True))).all()
        lista_solicitudes = db.session.scalars(select(SolicitudOficio).where(SolicitudOficio.estado == "pendiente")).all()
        for existente in [o.nombre for o in lista_catalogo] + [s.nombre_propuesto for s in lista_solicitudes]:
            if SequenceMatcher(None, clave, normalizar_nombre(existente)).ratio() >= 0.88:
                raise ErrorDominio(f"El nombre coincide o es muy parecido a «{existente}».")
        solicitud = SolicitudOficio(trabajador_id=trabajador.id, nombre_propuesto=nombre, nombre_normalizado=clave, descripcion=descripcion, estado="pendiente")
        db.session.add(solicitud)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("Ya hay una solicitud equivalente pendiente.")
        return solicitud

    def resolver_solicitud_oficio(self, solicitud, administrador, decision):
        if not isinstance(administrador, Administrador):
            raise ErrorDominio("Solo un administrador puede revisar oficios.")
        if solicitud.estado != "pendiente" or decision not in ("aprobado", "rechazado"):
            raise ErrorDominio("La solicitud ya fue resuelta o la decisión no es válida.")
        if decision == "aprobado":
            padre = db.session.scalar(select(Oficio).where(Oficio.nombre_normalizado == "oficios"))
            if not padre:
                raise ErrorDominio("Inicializa el catálogo de oficios antes de revisar propuestas.")
            clave = normalizar_nombre(solicitud.nombre_propuesto)
            existentes = db.session.scalars(select(Oficio).where(Oficio.activo.is_(True))).all()
            if any(SequenceMatcher(None, clave, normalizar_nombre(o.nombre)).ratio() >= 0.88 for o in existentes):
                raise ErrorDominio("No se puede aprobar: el catálogo ya contiene un oficio igual o muy similar.")
            self.agregar_oficio_aprobado(solicitud.nombre_propuesto, solicitud.descripcion, padre)
        solicitud.estado = decision
        solicitud.administrador_id = administrador.id
        solicitud.resuelta_en = datetime.now(timezone.utc)
        db.session.commit()
        self.reconstruir_indices()

    def agregar_oficio_aprobado(self, nombre, descripcion="", padre=None):
        clave = normalizar_nombre(nombre)
        of = Oficio(nombre=nombre.strip(), nombre_normalizado=clave, descripcion=(descripcion or "").strip(), padre=padre, activo=True)
        db.session.add(of)
        db.session.flush()
        return of

    def deshacer(self, actor_id=None):
        accion = self.historial.cima()
        if not accion:
            raise ErrorDominio("No hay acciones reversibles en esta ejecución.")
        if accion.actor_id is not None and accion.actor_id != actor_id:
            raise ErrorDominio("La última acción pertenece a otra cuenta; solo quien la realizó puede deshacerla.")
        if not accion.deshacer():
            raise ErrorDominio(f"No se pudo deshacer «{accion.descripcion}»: la acción ya no es compatible.")
        self.historial.remover_cima()
        return accion.descripcion

    @staticmethod
    def crear_proyecto(empresa, datos, oficio_ids):
        if not isinstance(empresa, Empresa):
            raise ErrorDominio("Solo una empresa puede publicar proyectos.")
        if not datos["nombre"].strip() or not datos["descripcion"].strip() or not datos["ubicacion"].strip():
            raise ErrorDominio("Completa nombre, descripción y ubicación del proyecto.")
        if not oficio_ids:
            raise ErrorDominio("Selecciona al menos un oficio requerido.")
        oficio_ids = Plataforma._ids_validos(oficio_ids, "oficios")
        oficios = db.session.scalars(select(Oficio).where(Oficio.id.in_(list(dict.fromkeys(oficio_ids))), Oficio.activo.is_(True))).all()
        if len(oficios) != len(set(oficio_ids)):
            raise ErrorDominio("Selecciona oficios aprobados.")
        proyecto = Proyecto(empresa=empresa, oficios=oficios, **datos)
        db.session.add(proyecto)
        db.session.commit()
        return proyecto

    @staticmethod
    def actualizar_proyecto(empresa, proyecto, datos, oficio_ids):
        if proyecto.empresa_id != empresa.id:
            raise ErrorDominio("Solo puedes modificar tus propios proyectos.")
        oficio_ids = Plataforma._ids_validos(oficio_ids, "oficios")
        oficios = db.session.scalars(select(Oficio).where(Oficio.id.in_(list(dict.fromkeys(oficio_ids))), Oficio.activo.is_(True))).all()
        if not oficios:
            raise ErrorDominio("Selecciona al menos un oficio aprobado.")
        for campo, valor in datos.items():
            setattr(proyecto, campo, valor)
        proyecto.oficios = oficios
        db.session.commit()

    @staticmethod
    def postular(trabajador, proyecto):
        if not isinstance(trabajador, Trabajador) or not trabajador.activo:
            raise ErrorDominio("Solo los trabajadores activos pueden postularse.")
        if proyecto.estado != "abierto":
            raise ErrorDominio("El proyecto ya no acepta postulaciones.")
        if not {o.id for o in proyecto.oficios}.intersection({o.id for o in trabajador.oficios}):
            raise ErrorDominio("El proyecto no requiere ninguno de tus oficios.")
        postulacion = Postulacion(proyecto=proyecto, trabajador=trabajador, estado="pendiente")
        db.session.add(postulacion)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise ErrorDominio("Ya te postulaste a este proyecto.")
        return postulacion

    @staticmethod
    def resolver_postulacion(empresa, postulacion, estado):
        if postulacion.proyecto.empresa_id != empresa.id:
            raise ErrorDominio("No puedes revisar postulaciones de otra empresa.")
        if estado not in ("aceptada", "rechazada") or postulacion.estado != "pendiente":
            raise ErrorDominio("La decisión o el estado de la postulación no es válido.")
        postulacion.estado = estado
        db.session.commit()


def seed_referencias():
    """Carga el catálogo base y zonas, de manera idempotente."""
    if not db.session.scalar(select(Oficio.id).limit(1)):
        root = Oficio(nombre="Oficios", nombre_normalizado="oficios", descripcion="Catálogo general")
        db.session.add(root)
        db.session.flush()
        for categoria, nombres in {
            "Construcción": ["Albañilería", "Pintura", "Carpintería"],
            "Instalaciones": ["Plomería", "Electricidad", "Aire acondicionado"],
        }.items():
            parent = Oficio(nombre=categoria, nombre_normalizado=normalizar_nombre(categoria), padre=root)
            db.session.add(parent)
            db.session.flush()
            for nombre in nombres:
                db.session.add(Oficio(nombre=nombre, nombre_normalizado=normalizar_nombre(nombre), padre=parent))
    for nombre in ["Asunción", "San Lorenzo", "Fernando de la Mora", "Luque", "Lambaré", "Capiatá", "Mariano Roque Alonso"]:
        if not db.session.scalar(select(Zona.id).where(Zona.nombre == nombre)):
            db.session.add(Zona(nombre=nombre, activa=True))
    for codigo, nombre in [("hogar", "Hogar"), ("empresarial", "Empresarial")]:
        if not db.session.scalar(select(CategoriaServicio.id).where(CategoriaServicio.codigo == codigo)):
            db.session.add(CategoriaServicio(codigo=codigo, nombre=nombre))
    db.session.flush()
    zone_ids = {z.nombre: z.id for z in db.session.scalars(select(Zona)).all()}
    for a, b in [("Asunción", "Lambaré"), ("Asunción", "Fernando de la Mora"), ("Fernando de la Mora", "San Lorenzo"), ("Fernando de la Mora", "Luque"), ("San Lorenzo", "Capiatá"), ("Luque", "Mariano Roque Alonso")]:
        low, high = sorted((zone_ids[a], zone_ids[b]))
        if not db.session.execute(select(zone_connections.c.zone_a_id).where(zone_connections.c.zone_a_id == low, zone_connections.c.zone_b_id == high)).first():
            db.session.execute(zone_connections.insert().values(zone_a_id=low, zone_b_id=high))
    db.session.commit()
