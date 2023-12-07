# eco_thermostat
Eco Thermostat for Home Assistant


**Example configuration:**

    - platform: eco_thermostat
      name: Calefaccio Planta 1 Eco
      unique_id: eco_calefaccio_planta_1
      heater: input_boolean.calefaccio
      target_sensor: sensor.temp_actual
      min_temp: 16
      max_temp: 23
      ac_mode: false
      target_temp: 19
      target_temp_step: 0.1
      cold_tolerance: 0.2
      hot_tolerance: -0.1
      min_cycle_duration:
        seconds: 10
      initial_hvac_mode: "heat"
      precision: 0.1
      #presets
      away_temp: 18
      comfort_temp: 21
      home_temp: 20
      sleep_temp: 18
      #new fields
      min_hot_tolerance: -0.1
      max_heating_locked: 
        #minutes: 15
        seconds: 30
      max_temp_jumps:
        - delta: -0.7
          tolerance: -0.3
        - delta: -0.6
          tolerance: -0.3
        - delta: -0.5
          tolerance: -0.2
        - delta: -0.4
          tolerance: -0.2
        - delta: -0.3
          tolerance: -0.1
        - delta: -0.2
          tolerance: -0.1
        - delta: -0.1
          tolerance: -0.1
      manual_timer: timer.temp_climate
      calendar_holidays: calendar.test_calendar
      schedule_temp:
        - start: '00:00'
          end: '06:59'
          temp: 18.5
        - start: '07:00'
          end: '07:29'
          temp: 20.0
        - start: '07:30'
          end: '13:29'
          temp: 19.5
        - start: '13:30'
          end: '15:29'
          temp: 20.5
        - start: '15:30'
          end: '18:29'
          temp: 19.5
        - start: '18:30'
          end: '23:29'
          temp: 21.0
        - start: '23:30'
          end: '23:59'
          temp: 20.0
      schedule_temp_holidays:
        - start: '00:00'
          end: '08:59'
          temp: 18.5
        - start: '09:00'
          end: '09:59'
          temp: 19.5
        - start: '10:00'
          end: '18:59'
          temp: 20.5
        - start: '19:00'
          end: '15:30'
          temp: 20.5
        - start: '23:29'
          end: '18:30'
          temp: 21.0
        - start: '23:30'
          end: '23:59'
          temp: 20.5

    #  TODO: 
    #  *new fields
    #   max_time_on: 30m
    #   time_delay_on: 10m
    #  *Expose new attributes "threshold_temp_sensor"
    #  *Expose action: "activate with delay if temperature low"

