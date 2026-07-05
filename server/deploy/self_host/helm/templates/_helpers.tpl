{{/* All shared bodies live here so the chart is split-ready (library-chart lift later). */}}

{{- define "donna.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "donna.fullname" -}}
{{- printf "%s-%s" .Release.Name (include "donna.name" .) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "donna.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{- define "donna.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "donna.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "donna.labels" -}}
app.kubernetes.io/name: {{ include "donna.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* envFrom the shared ConfigMap + the external Secret — every workload uses this */}}
{{- define "donna.envFrom" -}}
- configMapRef:
    name: {{ include "donna.fullname" . }}-config
- secretRef:
    name: {{ .Values.secrets.externalSecretName }}
{{- end -}}
