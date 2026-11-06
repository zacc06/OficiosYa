"""Implementaciones didácticas propias de estructuras de datos para OficiosYa."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional


@dataclass
class Nodo:
    dato: Any
    anterior: Optional["Nodo"] = None
    siguiente: Optional["Nodo"] = None


class ListaEnlazada:
    """Lista doblemente enlazada con inserción, búsqueda, eliminación y recorrido."""
    def __init__(self):
        self.cabeza: Optional[Nodo] = None
        self.cola: Optional[Nodo] = None
        self.tamano = 0

    def agregar(self, dato: Any) -> Nodo:
        nodo = Nodo(dato, anterior=self.cola)
        if self.cola:
            self.cola.siguiente = nodo
        else:
            self.cabeza = nodo
        self.cola = nodo
        self.tamano += 1
        return nodo

    def buscar(self, predicado: Callable[[Any], bool]) -> Any:
        actual = self.cabeza
        while actual:
            if predicado(actual.dato):
                return actual.dato
            actual = actual.siguiente
        return None

    def eliminar(self, predicado: Callable[[Any], bool]) -> Any:
        actual = self.cabeza
        while actual:
            if predicado(actual.dato):
                if actual.anterior:
                    actual.anterior.siguiente = actual.siguiente
                else:
                    self.cabeza = actual.siguiente
                if actual.siguiente:
                    actual.siguiente.anterior = actual.anterior
                else:
                    self.cola = actual.anterior
                actual.anterior = actual.siguiente = None
                self.tamano -= 1
                return actual.dato
            actual = actual.siguiente
        return None

    def __iter__(self) -> Iterator[Any]:
        actual = self.cabeza
        while actual:
            yield actual.dato
            actual = actual.siguiente

    def __len__(self):
        return self.tamano

    def como_lista(self):
        return list(iter(self))


class ColaFIFO:
    """Cola FIFO apoyada en nodos enlazados."""
    def __init__(self):
        self._items = ListaEnlazada()

    def encolar(self, elemento):
        self._items.agregar(elemento)

    def insertar_frente(self, elemento):
        """Restaura al frente un elemento al deshacer su atención FIFO."""
        nuevo = Nodo(elemento, siguiente=self._items.cabeza)
        if self._items.cabeza:
            self._items.cabeza.anterior = nuevo
        else:
            self._items.cola = nuevo
        self._items.cabeza = nuevo
        self._items.tamano += 1

    def desencolar(self):
        if not self._items.cabeza:
            return None
        primero = self._items.cabeza.dato
        self._items.eliminar(lambda x: x is primero)
        return primero

    def primero(self):
        return self._items.cabeza.dato if self._items.cabeza else None

    def contiene(self, predicado):
        return self._items.buscar(predicado) is not None

    def eliminar(self, predicado):
        return self._items.eliminar(predicado)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


@dataclass
class AccionReversible:
    descripcion: str
    deshacer: Callable[[], bool]
    actor_id: int | None = None


class PilaLIFO:
    """Pila LIFO; solo almacena operaciones que ofrecen una reversión real."""
    def __init__(self):
        self._items: list[AccionReversible] = []

    def apilar(self, accion: AccionReversible):
        self._items.append(accion)

    def desapilar(self):
        return self._items.pop() if self._items else None

    def cima(self):
        return self._items[-1] if self._items else None

    def remover_cima(self):
        return self._items.pop() if self._items else None

    def __len__(self):
        return len(self._items)

    def descripciones(self):
        return [a.descripcion for a in reversed(self._items)]


class NodoArbol:
    def __init__(self, nombre: str):
        self.nombre = nombre
        self.hijos: list[NodoArbol] = []


class ArbolOficios:
    def __init__(self, raiz="Oficios"):
        self.raiz = NodoArbol(raiz)

    def _buscar_nodo(self, nombre, nodo=None):
        nodo = nodo or self.raiz
        if nodo.nombre.casefold() == nombre.casefold():
            return nodo
        for hijo in nodo.hijos:
            encontrado = self._buscar_nodo(nombre, hijo)
            if encontrado:
                return encontrado
        return None

    def agregar(self, padre: str, nombre: str):
        padre_nodo = self._buscar_nodo(padre)
        if not padre_nodo:
            return False
        if self._buscar_nodo(nombre):
            return False
        padre_nodo.hijos.append(NodoArbol(nombre.strip()))
        return True

    def descendientes(self, categoria: str):
        nodo = self._buscar_nodo(categoria)
        if not nodo:
            return []
        resultado = []
        def recorrer(actual):
            resultado.append(actual.nombre)
            for hijo in actual.hijos:
                recorrer(hijo)
        recorrer(nodo)
        return resultado

    def contiene(self, nombre):
        return self._buscar_nodo(nombre) is not None

    def eliminar_subcategoria(self, nombre):
        """Elimina una hoja del árbol; no borra categorías con descendientes."""
        def buscar_padre(padre):
            for hijo in padre.hijos:
                if hijo.nombre.casefold() == nombre.casefold():
                    if hijo.hijos:
                        return False
                    padre.hijos.remove(hijo)
                    return True
                if buscar_padre(hijo):
                    return True
            return False
        return buscar_padre(self.raiz)

    def como_dict(self, nodo=None):
        nodo = nodo or self.raiz
        return {nodo.nombre: [self.como_dict(h) for h in nodo.hijos]}

    def filas(self):
        filas = []
        def recorrer(nodo, nivel=0):
            filas.append({"nombre": nodo.nombre, "nivel": nivel})
            for hijo in nodo.hijos:
                recorrer(hijo, nivel + 1)
        recorrer(self.raiz)
        return filas


class GrafoZonas:
    """Grafo no dirigido; el dict de adyacencia es almacenamiento auxiliar."""
    def __init__(self):
        self.adyacencia: dict[str, set[str]] = {}

    def agregar_zona(self, zona):
        self.adyacencia.setdefault(zona, set())

    def conectar(self, a, b):
        self.agregar_zona(a)
        self.agregar_zona(b)
        self.adyacencia[a].add(b)
        self.adyacencia[b].add(a)

    def bfs(self, inicio: str, max_distancia=1):
        if inicio not in self.adyacencia:
            return {}
        distancias = {inicio: 0}
        cola = [inicio]
        indice = 0
        while indice < len(cola):
            zona = cola[indice]
            indice += 1
            if distancias[zona] >= max_distancia:
                continue
            for vecina in sorted(self.adyacencia[zona]):
                if vecina not in distancias:
                    distancias[vecina] = distancias[zona] + 1
                    cola.append(vecina)
        return distancias

    def aristas(self):
        salida = []
        for zona, vecinos in sorted(self.adyacencia.items()):
            for vecino in sorted(vecinos):
                if zona < vecino:
                    salida.append((zona, vecino))
        return salida


class TablaHash:
    """Tabla hash propia con buckets encadenados y rehash automático."""
    def __init__(self, capacidad=8):
        self.capacidad = capacidad
        self.buckets: list[ListaEnlazada] = [ListaEnlazada() for _ in range(capacidad)]
        self.tamano = 0

    def _indice(self, clave):
        return sum((i + 1) * ord(c) for i, c in enumerate(str(clave))) % self.capacidad

    def insertar(self, clave, valor):
        indice = self._indice(clave)
        existente = self.buckets[indice].buscar(lambda par: par[0] == str(clave))
        if existente:
            self.buckets[indice].eliminar(lambda par: par[0] == str(clave))
            self.buckets[indice].agregar((str(clave), valor))
            return
        self.buckets[indice].agregar((str(clave), valor))
        self.tamano += 1
        if self.tamano / self.capacidad > 0.75:
            self._rehash(self.capacidad * 2)

    def buscar(self, clave):
        par = self.buckets[self._indice(clave)].buscar(lambda item: item[0] == str(clave))
        return par[1] if par else None

    def eliminar(self, clave):
        par = self.buckets[self._indice(clave)].eliminar(lambda item: item[0] == str(clave))
        if par:
            self.tamano -= 1
            return par[1]
        return None

    def _rehash(self, nueva_capacidad):
        pares = [par for bucket in self.buckets for par in bucket]
        self.capacidad = nueva_capacidad
        self.buckets = [ListaEnlazada() for _ in range(nueva_capacidad)]
        for clave, valor in pares:
            self.buckets[self._indice(clave)].agregar((clave, valor))

    def vista_buckets(self):
        return [[f"{clave}: {valor.nombre}" for clave, valor in bucket] for bucket in self.buckets]
