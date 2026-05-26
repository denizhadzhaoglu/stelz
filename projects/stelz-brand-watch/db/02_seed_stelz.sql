-- Seed data for STELZ as first tenant.
-- Run this after 01_schema.sql.

-- The brand itself
insert into brands (slug, name) values
  ('stelz', 'STËLZ')
on conflict (slug) do nothing;

-- Product lines
insert into brand_product_lines (brand_id, slug, name, description)
select b.id, v.slug, v.name, v.description
from brands b,
  (values
    ('hard_lemonade', 'STËLZ Hard Lemonade', 'White top + colored bottom slim cans, Cassis/Orange/Strawberry'),
    ('hard_seltzer', 'STËLZ Hard Seltzer', 'White slim cans with illustrated artwork, orange/red S logo'),
    ('hard_iced_tea', 'STËLZ Hard Iced Tea', 'Slim cans, Peach/Lime/Mango/Lemon variants')
  ) as v(slug, name, description)
where b.slug = 'stelz'
on conflict (brand_id, slug) do nothing;

-- Hashtag pools used in discovery
insert into brand_hashtag_pools (brand_id, hashtag, group_label, priority)
select b.id, v.hashtag, v.group_label, v.priority
from brands b,
  (values
    -- Direct brand
    ('stelz',                'brand_direct',  10),
    ('stelzhardseltzer',     'brand_direct',  10),
    ('stelzhardlemonade',    'brand_direct',  10),
    ('stelzhardicedtea',     'brand_direct',  10),
    -- Student life
    ('studentenleven',       'student_life',   7),
    ('studentlife',          'student_life',   7),
    ('introweek',            'student_life',   8),
    ('studentenstad',        'student_life',   6),
    -- House parties
    ('huisfeest',            'house_parties',  8),
    ('thuisfeest',           'house_parties',  8),
    ('huisfeestje',          'house_parties',  8),
    ('feestje',              'house_parties',  6),
    -- Drinks & borrels
    ('vrijmibo',             'drinks_borrel',  8),
    ('vrijdagmiddagborrel',  'drinks_borrel',  8),
    ('borrel',               'drinks_borrel',  7),
    ('werkborrel',           'drinks_borrel',  6),
    ('afterwork',            'drinks_borrel',  5),
    ('kerstborrel',          'drinks_borrel',  6),
    -- Friends
    ('vriendinnenuitje',     'friends',        7),
    ('vriendengroep',        'friends',        7),
    ('vrouwenuitje',         'friends',        6),
    ('ladiesnight',          'friends',        5),
    ('meidenavond',          'friends',        6),
    -- Festivals
    ('koningsdag',           'festivals',      9),
    ('kingsday',             'festivals',      8),
    ('zomerfeest',           'festivals',      7),
    ('festivalseizoen',      'festivals',      7),
    -- Going out
    ('nachtleven',           'going_out',      6),
    ('uitgaansleven',        'going_out',      6),
    ('gezelligheid',         'going_out',      5)
  ) as v(hashtag, group_label, priority)
where b.slug = 'stelz'
on conflict (brand_id, hashtag, platform) do nothing;

-- The active prompt (version 1, matching current 08_visual_scan_fast.py prompt)
insert into brand_prompt_config (brand_id, version, prompt_template, model, confidence_threshold, active)
select b.id, 1,
'You are a visual brand detector for STELZ, a Dutch alcoholic beverage brand. ...
(full prompt text -- placeholder, real prompt lives in the Python script and is synced via migration)',
'gemini-2.5-flash', 0.5, true
from brands b
where b.slug = 'stelz'
on conflict (brand_id, version) do nothing;
