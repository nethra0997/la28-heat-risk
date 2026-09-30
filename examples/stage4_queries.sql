-- Stage 4: learning SQL on the warehouse. Each query teaches one idea.
-- Run all of them:  uv run python -m examples.run_sql examples/stage4_queries.sql
-- Lines starting with -- are comments; the first comment of each query is printed as its title.


-- Q1. SELECT + LIMIT: look at a few rows of a table
select venue_label, exposure, region, loc_id
from venues
limit 5;


-- Q2. WHERE: keep only the rows that match a condition
select venue_label, exposure
from venues
where exposure = 'outdoor'
  and region = 'la_metro';


-- Q3. ORDER BY: the 10 most heat-stressful hours at the Coliseum (loc_id 34.014_-118.288)
select time_local, temperature_2m, relative_humidity_2m, wbgt_sun_c
from weather_wbgt
where loc_id = '34.014_-118.288'
order by wbgt_sun_c desc
limit 10;


-- Q4. GROUP BY: one summary row per place (count, average, maximum)
select loc_id,
       count(*)                  as hours,
       round(avg(wbgt_sun_c), 1) as avg_wbgt,
       round(max(wbgt_sun_c), 1) as max_wbgt
from weather_wbgt
group by loc_id
order by max_wbgt desc
limit 10;


-- Q5. JOIN: attach venue names to the weather (the tables share the loc_id column)
select v.venue_label,
       v.exposure,
       round(max(w.wbgt_sun_c), 1) as max_wbgt
from venues v
join weather_wbgt w on w.loc_id = v.loc_id
group by v.venue_label, v.exposure
order by max_wbgt desc
limit 10;


-- Q6. CASE: turn a number into a category (the heat flags)
select case
         when wbgt_sun_c >= 32.2 then '5 black'
         when wbgt_sun_c >= 31.1 then '4 red'
         when wbgt_sun_c >= 29.4 then '3 yellow'
         when wbgt_sun_c >= 26.7 then '2 green'
         else '1 none'
       end      as flag,
       count(*) as hours
from weather_wbgt
group by flag
order by flag;


-- Q7. Putting it together: red or black flag hours per outdoor LA-area venue, daytime only
select v.venue_label,
       count(*) filter (where w.wbgt_sun_c >= 31.1) as red_or_black_hours,
       round(max(w.wbgt_sun_c), 1)                  as max_wbgt
from venues v
join weather_wbgt w on w.loc_id = v.loc_id
where v.exposure = 'outdoor'
  and v.region = 'la_metro'
  and hour(w.time_local) between 8 and 20
group by v.venue_label
order by red_or_black_hours desc
limit 10;
