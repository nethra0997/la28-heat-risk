{# Use the configured schema name as-is (staging/silver/gold) instead of dbt's
   default "<target_schema>_<custom_schema>" so Tableau/Streamlit see clean names. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
