-- MaxVolt Battery Models — Seed Data
-- welding_type: 'LASER' | 'SPOT'  (enum names as stored by SQLAlchemy in Postgres)
-- cell_type:    'NMC'   | 'LFP'

INSERT INTO battery_models (model_id, category, series_count, parallel_count, cell_type, bms_model, welding_type)
VALUES
  ('48V 25AH E-Scooter Lithium Battery Eco', '2-Wheeler', 13, 9, 'NMC', '17S 40A JBD', 'SPOT'),
  ('48V 29AH E-Scooter Lithium Battery Eco', '2-Wheeler', 13, 11, 'NMC', '17S 40A JBD', 'SPOT'),
  ('48V 40AH E-Scooter Lithium Battery Eco', '2-Wheeler', 13, 15, 'NMC', '17S 40A JBD', 'SPOT'),
  ('60V 25AH E-Scooter Lithium Battery Eco', '2-Wheeler', 16, 9, 'NMC', '17S 40A JBD', 'SPOT'),
  ('60V 29AH E-Scooter Lithium Battery Eco', '2-Wheeler', 16, 11, 'NMC', '17S 40A JBD', 'SPOT'),
  ('60V 34AH E-Scooter Lithium Battery Eco', '2-Wheeler', 16, 13, 'NMC', '17S 40A JBD', 'SPOT'),
  ('60V 40AH E-Scooter Lithium Battery Eco', '2-Wheeler', 16, 15, 'NMC', '17S 40A JBD', 'SPOT'),
  ('74V 25AH E-Scooter Lithium Battery Eco', '2-Wheeler', 20, 9, 'NMC', '24S 60A JBD', 'SPOT'),
  ('74V 29AH E-Scooter Lithium Battery Eco', '2-Wheeler', 20, 11, 'NMC', '24S 60A JBD', 'SPOT'),
  ('48V 29AH E-Scooter Lithium Battery-A', '2-Wheeler', 13, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('48V 29AH E-Scooter Lithium Battery-B', '2-Wheeler', 13, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('62.9V 29AH E-Scooter Lithium Battery-A', '2-Wheeler', 17, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('62.9V 29AH E-Scooter Lithium Battery-B', '2-Wheeler', 17, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('62.9V 34AH E-Scooter Lithium Battery', '2-Wheeler', 17, 13, 'NMC', '20S 40A JK', 'SPOT'),
  ('62.9V 40AH E-Scooter Lithium Battery', '2-Wheeler', 17, 15, 'NMC', '20S 40A JK', 'SPOT'),
  ('74V 29AH E-Scooter Lithium Battery', '2-Wheeler', 20, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('74V 34AH E-Scooter Lithium Battery', '2-Wheeler', 20, 13, 'NMC', '20S 40A JK', 'SPOT'),
  ('74V 40AH E-Scooter Lithium Battery', '2-Wheeler', 20, 15, 'NMC', '20S 40A JK', 'SPOT'),
  ('48V 34AH E-Scooter Lithium Battery', '2-Wheeler', 13, 13, 'NMC', '20S 40A JK', 'SPOT'),
  ('48V 40AH E-Scooter Lithium Battery', '2-Wheeler', 13, 15, 'NMC', '20S 40A JK', 'SPOT'),
  ('62.9V 29AH E-Scooter Lithium Battery - CD', '2-Wheeler', 17, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('48V 29 AH E-Scooter Lithium Battery - CD', '2-Wheeler', 13, 11, 'NMC', '20S 40A JK', 'SPOT'),
  ('51.2V 105AH E-Rickshaw Lithium Battery', '3-Wheeler', 16, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('51.2V 150AH E-Rickshaw Lithium Battery', '3-Wheeler', 16, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('51.2V 200AH E-Rickshaw Lithium Battery', '3-Wheeler', 16, 2, 'LFP', '24S 100A JK', 'LASER'),
  ('64V 105AH E-Rickshaw Lithium Battery', '3-Wheeler', 20, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('64V 150AH E-Rickshaw Lithium Battery', '3-Wheeler', 20, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('74V 105AH E-Rickshaw Lithium Battery', '3-Wheeler', 23, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('74V 150AH E-Rickshaw Lithium Battery', '3-Wheeler', 23, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('12.8V 100AH Solar lithium battery', 'ESS', 4, 1, 'LFP', '4S 100A DALY', 'LASER'),
  ('12.8V 150AH Solar lithium battery', 'ESS', 4, 1, 'LFP', '4S 100A DALY', 'LASER'),
  ('25.6V 100AH Solar lithium battery', 'ESS', 8, 1, 'LFP', '8S 100A DALY', 'LASER'),
  ('25.6V 150AH Solar lithium battery', 'ESS', 8, 1, 'LFP', '8S 100A DALY', 'LASER'),
  ('48V 100AH SOLAR LITHIUM BATTERY', 'ESS', 15, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('48V 100AH SOLAR LITHIUM BATTERY-1C', 'ESS', 15, 1, 'LFP', '16S 100A JK', 'LASER'),
  ('51.2V 100AH SOLAR LITHIUM BATTERY', 'ESS', 16, 1, 'LFP', '24S 100A JK', 'LASER'),
  ('51.2V 100AH SOLAR LITHIUM BATTERY-1C', 'ESS', 16, 1, 'LFP', '16S 100A JK', 'LASER'),
  ('25.6V 48AH SOLAR LITHIUM BATTERY', 'ESS', 8, 8, 'LFP', '8S 100A DALY', 'LASER'),
  ('25.6V 100AH SOLAR LITHIUM BATTERY 1C', 'ESS', 8, 1, 'LFP', '16S 100A JK', 'LASER');

-- Total: 39 models