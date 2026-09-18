# Guía de Evaluación y Rúbrica para la Cátedra
## Plataforma de Observabilidad, Seguimiento PERT/CPM y Daily Scrum Serverless

> **Aviso para la Cátedra / Docente Evaluador:**  
> Este sistema no constituye el Trabajo Práctico en sí mismo; es la **plataforma integral de gestión, trazabilidad y observabilidad** construida ex profeso para que el equipo docente pueda evaluar con métricas objetivas y datos en tiempo real el desarrollo del Trabajo Práctico principal.

---

## 1. Justificación Arquitectónica y Metodológica

Para la evaluación del Trabajo Práctico, el equipo implementó una arquitectura **100% Serverless en AWS Free Tier** que resuelve las limitaciones clásicas del trabajo en grupo universitario (falta de visibilidad individual, bloqueos ocultos, tareas no declaradas y asimetría de aportes).

### Pilares de la Solución
1. **Single Table Design en Amazon DynamoDB**:
   - Modelo de datos unificado con particiones (`PROJECT#`, `TASK#`, `USER#`, `AUDIT#`, `WEEK#DAY#MEMBER#`).
   - Consultas O(1) y transacciones acotadas a 1 RCU / 1 WCU sin costos de infraestructura.
2. **Microservicios en AWS Lambda (Python 3.11)**:
   - Backend idempotente sin dependencias pesadas de terceros.
   - Seguridad con Tokens de Sesión HMAC-SHA256 y RBAC estricto (los integrantes solo pueden editar sus propias Dailies; los administradores consolidan la visión de equipo).
3. **Gestión de Dependencias en Vivo (PERT / CPM)**:
   - Red visual de actividades en nodo (AON) donde las tareas bloqueantes forman la **Ruta Crítica** en tiempo real.
   - Enlace directo entre impedimentos declarados en Daily Scrum y tareas en el tablero Kanban.
4. **Auditoría Criptográfica de Accesos**:
   - Registro inmutable de signups, activaciones de cuenta, logins y direcciones IP.
   - Visualización de recurrencia y presencia de cada alumno a lo largo de las semanas de cursada.

---

## 2. Rúbrica de Calificación Sugerida (Escala 1 al 10)

| Dimensión | Ponderación | Criterios de Excelencia (Nota 10) |
| :--- | :---: | :--- |
| **1. Arquitectura Cloud & Serverless** | **2.5 pts** | Adhesión a AWS Free Tier, Single Table Design en DynamoDB, Lambda con Python nativo, tokens firmados HMAC-SHA256, SMTP transaccional para activación de cuentas. |
| **2. Metodología Ágil & Dinámica de Scrum** | **2.5 pts** | Cadencia semanal de Daily Scrum, sincronización bidireccional inmediata con Tablero Kanban (Scrumban), respuesta transparente a las 3 preguntas clásicas. |
| **3. Gestión de Dependencias & PERT/CPM** | **2.5 pts** | Visualización gráfica del flujo de trabajo, identificación clara de cuellos de botella ("¿Quién traba a quién?"), cálculo del tiempo trabado y asignación rápida de tareas bloqueantes. |
| **4. Compromiso Individual & Trazabilidad** | **2.5 pts** | Participación homogénea verificada por el módulo de auditoría de actividad (fechas de login, cantidad de accesos, creación y resolución de tareas asignadas). |

---

## 3. Guía Paso a Paso para la Evaluación Docente

### Paso 1: Verificación de Presencia y Accesos (Auditoría de Usuarios)
1. Inicie sesión con la cuenta de administrador / docente.
2. Diríjase a la pestaña **`📈 Flujo & Bloqueos`**.
3. En la sección **`👥 Auditoría de Actividad del Equipo`**, observe:
   - **Fecha de Registro / Activación**: Cuándo se incorporó cada integrante al entorno.
   - **Último Ingreso**: Cuán reciente fue la última interacción del estudiante.
   - **Historial de Logins**: Nivel de actividad y constancia durante el sprint.
   - **Trazabilidad de Sesiones**: Eventos cronológicos con timestamp e IP.

### Paso 2: Análisis de Flujo y Cuellos de Botella (Diagnóstico)
1. Observe la fila superior de KPIs:
   - **Bloqueos Activos**: Porcentaje del equipo detenido por dependencias.
   - **Tiempo Promedio Trabado**: Horas o días que un integrante permanece esperando resolución.
   - **Cuello de Botella Crítico**: Identificación algorítmica del integrante o recurso que frena a mayor cantidad de compañeros.
2. Revise la tabla **"¿Quién traba a quién?"**:
   - Diagnóstico cruzado entre responsables y dependencias no resueltas.

### Paso 3: Inspección de la Red PERT/CPM en Vivo
1. En la vista de Diagnóstico, despliegue el **Grafo Interactivo PERT/CPM**:
   - **Nodos Rojos / Bordes Animados**: Tareas que forman la **Ruta Crítica** porque están retrasando a otros integrantes.
   - **Nodos Verdes**: Tareas completadas que liberaron el flujo.
   - **Flechas Direccionales**: Dependencias explicitadas entre tareas y miembros.
2. Compruebe cómo la declaración de un bloqueo en el Daily Scrum genera automáticamente la dependencia en el grafo.

### Paso 4: Comprobación del Tablero Kanban y Sincronización
1. Cambie a la pestaña **`📋 Tablero Kanban`**.
2. Verifique la coherencia entre las tareas en progreso (`DOING`), bloqueadas (`BLOCKED`) y completadas (`DONE`) respecto a las respuestas cargadas en la matriz semanal.

---

## 4. Conclusión para la Cátedra

Esta herramienta demuestra la capacidad del equipo no solo de codificar la aplicación solicitada en el Trabajo Práctico, sino de **gobernar un ciclo de vida de desarrollo de software profesional**:
- Visibilidad radical sin intermediarios.
- Resolución proactiva de bloqueos.
- Evidencia empírica de autoría y trabajo en equipo.
