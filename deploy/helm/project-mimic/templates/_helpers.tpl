{{- define "project-mimic.namespace" -}}
{{ .Values.global.namespace }}
{{- end -}}

{{- define "project-mimic.labels" -}}
app.kubernetes.io/managed-by: Helm
app.kubernetes.io/part-of: project-mimic
{{- end -}}
