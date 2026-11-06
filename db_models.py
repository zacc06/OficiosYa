"""Modelos SQLAlchemy del estado persistente de OficiosYa."""
from __future__ import annotations

from datetime import datetime, timezone
from werkzeug.security import check_password_hash, generate_password_hash
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, UniqueConstraint, Index

from extensions import db


worker_offices = db.Table(
    "worker_offices",
    db.Column("worker_id", db.ForeignKey("worker_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("office_id", db.ForeignKey("offices.id", ondelete="RESTRICT"), primary_key=True),
)
worker_zones = db.Table(
    "worker_zones",
    db.Column("worker_id", db.ForeignKey("worker_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("zone_id", db.ForeignKey("zones.id", ondelete="RESTRICT"), primary_key=True),
)
worker_service_categories = db.Table(
    "worker_service_categories",
    db.Column("worker_id", db.ForeignKey("worker_profiles.id", ondelete="CASCADE"), primary_key=True),
    db.Column("category_id", db.ForeignKey("service_categories.id", ondelete="RESTRICT"), primary_key=True),
)
project_offices = db.Table(
    "project_offices",
    db.Column("project_id", db.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    db.Column("office_id", db.ForeignKey("offices.id", ondelete="RESTRICT"), primary_key=True),
)
service_category_links = db.Table(
    "service_category_links",
    db.Column("service_id", db.ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
    db.Column("category_id", db.ForeignKey("service_categories.id", ondelete="RESTRICT"), primary_key=True),
)
zone_connections = db.Table(
    "zone_connections",
    db.Column("zone_a_id", db.ForeignKey("zones.id", ondelete="CASCADE"), primary_key=True),
    db.Column("zone_b_id", db.ForeignKey("zones.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("zone_a_id < zone_b_id", name="ordered_undirected_edge"),
)


def utcnow():
    return datetime.now(timezone.utc)


class Usuario(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), unique=True, index=True)
    nombre = db.Column(db.String(80), nullable=False)
    apellido = db.Column(db.String(80), nullable=False)
    correo = db.Column(db.String(254), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    telefono = db.Column(db.String(32), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    registrado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    activo = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (CheckConstraint("role IN ('cliente','trabajador','empresa','administrador')", name="valid_role"),)
    __mapper_args__ = {"polymorphic_on": role, "polymorphic_identity": "base"}

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password or "")

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}".strip()

    @property
    def is_active(self):
        return self.activo

    def get_id(self):
        return str(self.id)


class Cliente(Usuario):
    __mapper_args__ = {"polymorphic_identity": "cliente"}
    servicios = db.relationship("Solicitud", back_populates="cliente", foreign_keys="Solicitud.cliente_id")


class Administrador(Usuario):
    __mapper_args__ = {"polymorphic_identity": "administrador"}


class Trabajador(Usuario):
    __tablename__ = "worker_profiles"
    id = db.Column(db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    descripcion_profesional = db.Column(db.Text, nullable=False, default="")
    ubicacion = db.Column(db.String(160), nullable=False, default="")
    experiencia_anios = db.Column(db.Integer, nullable=False, default=0)
    foto_perfil = db.Column(db.String(500))
    oficios = db.relationship("Oficio", secondary=worker_offices, back_populates="trabajadores", lazy="selectin")
    zonas = db.relationship("Zona", secondary=worker_zones, back_populates="trabajadores", lazy="selectin")
    categorias_servicio = db.relationship("CategoriaServicio", secondary=worker_service_categories, lazy="selectin")
    servicios = db.relationship("Solicitud", back_populates="trabajador", foreign_keys="Solicitud.trabajador_id")
    postulaciones = db.relationship("Postulacion", back_populates="trabajador")
    __mapper_args__ = {"polymorphic_identity": "trabajador"}

    @property
    def promedio(self):
        puntuaciones = [s.valoracion.puntuacion for s in self.servicios if s.valoracion]
        return round(sum(puntuaciones) / len(puntuaciones), 1) if puntuaciones else 0.0


class Empresa(Usuario):
    __tablename__ = "companies"
    id = db.Column(db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    nombre_empresa = db.Column(db.String(160), nullable=False)
    ruc = db.Column(db.String(32), nullable=False, unique=True)
    direccion = db.Column(db.String(240), nullable=False)
    telefono_empresa = db.Column(db.String(32), nullable=False)
    correo_empresa = db.Column(db.String(254), nullable=False)
    descripcion = db.Column(db.Text, nullable=False, default="")
    proyectos = db.relationship("Proyecto", back_populates="empresa", cascade="all, delete-orphan")
    __mapper_args__ = {"polymorphic_identity": "empresa"}


class Oficio(db.Model):
    __tablename__ = "offices"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    nombre_normalizado = db.Column(db.String(140), nullable=False, unique=True)
    descripcion = db.Column(db.Text, nullable=False, default="")
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    parent_id = db.Column(db.ForeignKey("offices.id", ondelete="RESTRICT"))
    padre = db.relationship("Oficio", remote_side=[id], back_populates="hijos")
    hijos = db.relationship("Oficio", back_populates="padre")
    trabajadores = db.relationship("Trabajador", secondary=worker_offices, back_populates="oficios")


class Zona(db.Model):
    __tablename__ = "zones"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False, unique=True)
    activa = db.Column(db.Boolean, nullable=False, default=True)
    trabajadores = db.relationship("Trabajador", secondary=worker_zones, back_populates="zonas")


class SolicitudOficio(db.Model):
    __tablename__ = "office_requests"
    id = db.Column(db.Integer, primary_key=True)
    trabajador_id = db.Column(db.ForeignKey("worker_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    nombre_propuesto = db.Column(db.String(120), nullable=False)
    nombre_normalizado = db.Column(db.String(140), nullable=False, index=True)
    descripcion = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(16), nullable=False, default="pendiente", index=True)
    administrador_id = db.Column(db.ForeignKey("users.id", ondelete="SET NULL"))
    solicitada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    resuelta_en = db.Column(db.DateTime(timezone=True))
    trabajador = db.relationship("Trabajador", foreign_keys=[trabajador_id])
    administrador = db.relationship("Usuario", foreign_keys=[administrador_id])
    __table_args__ = (CheckConstraint("estado IN ('pendiente','aprobado','rechazado')", name="valid_office_request_state"),)


class Proyecto(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    nombre = db.Column(db.String(180), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    trabajadores_necesarios = db.Column(db.Integer, nullable=False)
    ubicacion = db.Column(db.String(180), nullable=False)
    inicio_estimado = db.Column(db.Date, nullable=False)
    duracion_dias = db.Column(db.Integer, nullable=False)
    presupuesto = db.Column(db.Numeric(14, 2))
    estado = db.Column(db.String(16), nullable=False, default="abierto", index=True)
    creado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    actualizado_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    empresa = db.relationship("Empresa", back_populates="proyectos")
    oficios = db.relationship("Oficio", secondary=project_offices, lazy="selectin")
    postulaciones = db.relationship("Postulacion", back_populates="proyecto", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("trabajadores_necesarios > 0", name="positive_workers_needed"),
        CheckConstraint("duracion_dias > 0", name="positive_duration"),
        CheckConstraint("presupuesto IS NULL OR presupuesto >= 0", name="nonnegative_budget"),
        CheckConstraint("estado IN ('abierto','en_proceso','finalizado')", name="valid_project_state"),
    )


class Postulacion(db.Model):
    __tablename__ = "applications"
    id = db.Column(db.Integer, primary_key=True)
    proyecto_id = db.Column(db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    trabajador_id = db.Column(db.ForeignKey("worker_profiles.id", ondelete="CASCADE"), nullable=False)
    postulada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    estado = db.Column(db.String(16), nullable=False, default="pendiente", index=True)
    proyecto = db.relationship("Proyecto", back_populates="postulaciones")
    trabajador = db.relationship("Trabajador", back_populates="postulaciones")
    __table_args__ = (
        UniqueConstraint("proyecto_id", "trabajador_id", name="uq_application_project_worker"),
        CheckConstraint("estado IN ('pendiente','aceptada','rechazada','retirada')", name="valid_application_state"),
    )


class CategoriaServicio(db.Model):
    __tablename__ = "service_categories"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), nullable=False, unique=True)
    nombre = db.Column(db.String(40), nullable=False, unique=True)
    __table_args__ = (CheckConstraint("codigo IN ('hogar','empresarial')", name="valid_service_category"),)


class Solicitud(db.Model):
    """Solicitud original persistida como servicio, con cola FIFO runtime."""
    __tablename__ = "services"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(32), nullable=False, unique=True, index=True)
    cliente_id = db.Column(db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    trabajador_id = db.Column(db.ForeignKey("worker_profiles.id", ondelete="SET NULL"), index=True)
    descripcion = db.Column(db.Text, nullable=False)
    oficio_id = db.Column(db.ForeignKey("offices.id", ondelete="RESTRICT"), nullable=False)
    zona_id = db.Column(db.ForeignKey("zones.id", ondelete="RESTRICT"))
    ubicacion = db.Column(db.String(240), nullable=False, default="")
    estado = db.Column(db.String(16), nullable=False, default="pendiente", index=True)
    creada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    cliente = db.relationship("Cliente", back_populates="servicios", foreign_keys=[cliente_id])
    trabajador = db.relationship("Trabajador", back_populates="servicios", foreign_keys=[trabajador_id])
    oficio = db.relationship("Oficio")
    zona = db.relationship("Zona")
    categorias = db.relationship("CategoriaServicio", secondary=service_category_links, lazy="selectin")
    valoracion = db.relationship("Valoracion", back_populates="servicio", uselist=False, cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("estado IN ('pendiente','en_proceso','finalizada','cancelada')", name="valid_service_state"),)


class Valoracion(db.Model):
    __tablename__ = "ratings"
    id = db.Column(db.Integer, primary_key=True)
    servicio_id = db.Column(db.ForeignKey("services.id", ondelete="CASCADE"), nullable=False, unique=True)
    cliente_id = db.Column(db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    trabajador_id = db.Column(db.ForeignKey("worker_profiles.id", ondelete="RESTRICT"), nullable=False)
    puntuacion = db.Column(db.SmallInteger, nullable=False)
    comentario = db.Column(db.String(1000), nullable=False, default="")
    creada_en = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    servicio = db.relationship("Solicitud", back_populates="valoracion")
    __table_args__ = (CheckConstraint("puntuacion BETWEEN 1 AND 5", name="rating_between_one_and_five"),)


Index("ix_projects_open_start", Proyecto.estado, Proyecto.inicio_estimado)
Index("ix_services_worker_queue", Solicitud.trabajador_id, Solicitud.estado, Solicitud.creada_en, Solicitud.id)
Index("ix_office_requests_pending", SolicitudOficio.estado, SolicitudOficio.solicitada_en)
