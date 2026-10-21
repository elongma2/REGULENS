begin;
select plan(14);

select has_table('public', 'cases', 'cases table exists');
select has_table('public', 'formulation_versions', 'formulation versions table exists');
select has_table('public', 'clarifications', 'clarifications table exists');
select has_table('public', 'screening_runs', 'screening runs table exists');
select has_table('public', 'review_items', 'review items table exists');
select has_table('public', 'reviewer_notes', 'reviewer notes table exists');
select has_table('public', 'follow_up_actions', 'follow-up actions table exists');
select policies_are('public', 'cases', array['cases_select_member', 'cases_insert_member', 'cases_update_member', 'cases_delete_member']);
select policies_are('public', 'formulation_versions', array['formulation_versions_select_member', 'formulation_versions_insert_member', 'formulation_versions_update_member', 'formulation_versions_delete_member']);
select policies_are('public', 'clarifications', array['clarifications_select_member', 'clarifications_insert_member', 'clarifications_update_member', 'clarifications_delete_member']);
select policies_are('public', 'screening_runs', array['screening_runs_select_member']);
select policies_are('public', 'review_items', array['review_items_select_member', 'review_items_update_member']);
select policies_are('public', 'reviewer_notes', array['reviewer_notes_select_member', 'reviewer_notes_insert_member']);
select policies_are('public', 'follow_up_actions', array['follow_up_actions_select_member', 'follow_up_actions_insert_member', 'follow_up_actions_update_member']);

select * from finish();
rollback;
