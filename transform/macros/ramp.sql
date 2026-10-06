{# Linear 0-100 score: lo -> 0, hi -> 100, clamped. NULL in -> NULL out.
   (DuckDB's greatest/least skip NULLs, so greatest(NULL, 0) would silently return 0.) #}
{% macro ramp(expr, lo, hi) -%}
    case when ({{ expr }}) is null then null
         else least(greatest((({{ expr }}) - ({{ lo }})) / (({{ hi }}) - ({{ lo }})), 0), 1) * 100 end
{%- endmacro %}
