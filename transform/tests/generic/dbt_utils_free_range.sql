{# Minimal range test (avoids pulling in the dbt_utils package). Nulls pass. #}
{% test dbt_utils_free_range(model, column_name, min_value, max_value) %}
select *
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
