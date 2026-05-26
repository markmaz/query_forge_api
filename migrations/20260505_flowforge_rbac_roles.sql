INSERT INTO roles (name, display_name, description, feature_key, is_system)
SELECT 'flowforge:viewer',
       'FlowForge Viewer',
       'View FlowForge runs, reports, workflows, and resource snapshots.',
       'flowforge',
       1
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'flowforge:viewer');

INSERT INTO roles (name, display_name, description, feature_key, is_system)
SELECT 'flowforge:operator',
       'FlowForge Operator',
       'Operate FlowForge runs, create signed actions, add run notes, and handle escalations.',
       'flowforge',
       1
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'flowforge:operator');

INSERT INTO roles (name, display_name, description, feature_key, is_system)
SELECT 'flowforge:designer',
       'FlowForge Designer',
       'Design FlowForge workflows, matching policies, resources, and integrations.',
       'flowforge',
       1
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'flowforge:designer');
