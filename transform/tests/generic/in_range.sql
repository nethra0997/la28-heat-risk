{# Reusable test: fails for any row where the column is outside [min_value, max_value].
   A dbt test is a query that returns the BAD rows; zero rows returned = test passes.
   Nulls pass (use not_null to check for those). #}
{% test in_range(model, column_name, min_value, max_value) %}
select *
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
