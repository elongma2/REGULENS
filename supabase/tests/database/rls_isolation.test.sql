begin;
select plan(26);

insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, email_change, email_change_token_new, recovery_token
) values
    ('00000000-0000-0000-0000-000000000000', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'authenticated', 'authenticated',
     'a@example.test', crypt('password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}',
     '{"display_name":"User A"}', now(), now(), '', '', '', ''),
    ('00000000-0000-0000-0000-000000000000', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'authenticated', 'authenticated',
     'b@example.test', crypt('password', gen_salt('bf')), now(), '{"provider":"email","providers":["email"]}',
     '{"display_name":"User B"}', now(), now(), '', '', '', '');

select is((select count(*) from public.profiles where id in (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
)), 2::bigint, 'signup trigger creates both profiles');
select is((select count(*) from public.organisation_members where user_id in (
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
) and role = 'owner'), 2::bigint, 'signup trigger creates an owner workspace for each user');

insert into public.cases (id, organisation_id, name, created_by)
select '11111111-aaaa-4aaa-8aaa-111111111111', organisation_id, 'User A Serum', user_id
from public.organisation_members where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

insert into public.formulation_versions (
    id, case_id, version_number, original_filename, status, revision, raw_extraction, agent_state, created_by
) values (
    '11111111-bbbb-4bbb-8bbb-111111111111', '11111111-aaaa-4aaa-8aaa-111111111111', 1,
    'serum.csv', 'clarification_required', 1, '{"rows":[["Ingredient"],["NIACINAMIDE"]]}',
    '{"state":"needs_confirmation"}', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.clarifications (
    id, formulation_version_id, question_key, row_id, field_name, question
) values (
    '11111111-cccc-4ccc-8ccc-111111111111', '11111111-bbbb-4bbb-8bbb-111111111111',
    'unit:row-2', 'row-2', 'concentration.unit', 'Choose the concentration unit.'
);

insert into public.screening_runs (
    id, formulation_version_id, regulatory_dataset_id, jurisdiction, request_snapshot, result_snapshot, created_by
) values (
    '11111111-dddd-4ddd-8ddd-111111111111', '11111111-bbbb-4bbb-8bbb-111111111111',
    'accepted-test-version', 'Singapore', '{}', '{"marker":"original"}', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.review_items (
    id, screening_run_id, subject_key, submitted_row_number, engine_finding,
    requires_attention, review_status, updated_by
) values (
    '11111111-ffff-4fff-8fff-111111111111', '11111111-dddd-4ddd-8ddd-111111111111',
    'ingredient:1', 1, 'information_missing', true, 'not_reviewed',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.reviewer_notes (
    id, case_id, review_item_id, body, created_by
) values (
    '33333333-aaaa-4aaa-8aaa-111111111111', '11111111-aaaa-4aaa-8aaa-111111111111',
    '11111111-ffff-4fff-8fff-111111111111', 'Confirm the missing basis.',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into public.follow_up_actions (
    id, case_id, review_item_id, action_text, created_by
) values (
    '33333333-bbbb-4bbb-8bbb-111111111111', '11111111-aaaa-4aaa-8aaa-111111111111',
    '11111111-ffff-4fff-8fff-111111111111', 'Request the missing basis.',
    'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
);

insert into storage.objects (bucket_id, name)
select 'formulation-files', organisation_id::text || '/11111111-aaaa-4aaa-8aaa-111111111111/11111111-bbbb-4bbb-8bbb-111111111111/serum.csv'
from public.organisation_members where user_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

do $$
begin
    perform public.create_formulation_version(
        '11111111-eeee-4eee-8eee-111111111111',
        '11111111-aaaa-4aaa-8aaa-111111111111',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        'serum-v2.csv', 'private/path/serum-v2.csv', '{"rows":[]}', '{"revision":0,"state":"parsing"}'
    );
    perform public.persist_formulation_state(
        '11111111-bbbb-4bbb-8bbb-111111111111',
        'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        1, 'interpreted', '{"revision":2,"state":"interpreted"}', null, null, '[]'
    );
end;
$$;

select is((select version_number from public.formulation_versions where id = '11111111-eeee-4eee-8eee-111111111111'), 2, 'second upload receives version 2');
select is((select status from public.clarifications where id = '11111111-cccc-4ccc-8ccc-111111111111'), 'resolved', 'resolved clarification state persists');

set local role authenticated;
select set_config('request.jwt.claim.sub', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', true);
select is((select count(*) from public.cases where id = '11111111-aaaa-4aaa-8aaa-111111111111'), 1::bigint, 'User A can select their case');
select is((select count(*) from public.formulation_versions where id = '11111111-bbbb-4bbb-8bbb-111111111111'), 1::bigint, 'User A can select their formulation');
select is((select count(*) from public.clarifications where id = '11111111-cccc-4ccc-8ccc-111111111111'), 1::bigint, 'User A can select their clarification');
select is((select count(*) from public.screening_runs where id = '11111111-dddd-4ddd-8ddd-111111111111'), 1::bigint, 'User A can select their screening');
select is((select count(*) from public.review_items where id = '11111111-ffff-4fff-8fff-111111111111'), 1::bigint, 'User A can select their review item');
select is((select count(*) from public.reviewer_notes where id = '33333333-aaaa-4aaa-8aaa-111111111111'), 1::bigint, 'User A can select their reviewer note');
select is((select count(*) from public.follow_up_actions where id = '33333333-bbbb-4bbb-8bbb-111111111111'), 1::bigint, 'User A can select their follow-up');
select is((select count(*) from storage.objects where name like '%/serum.csv'), 1::bigint, 'User A can select their private file');

select throws_ok(
    $$update public.review_items set engine_finding = 'restriction_exceeded' where id = '11111111-ffff-4fff-8fff-111111111111'$$,
    '23514', 'review_item_engine_fields_are_immutable',
    'User A cannot alter the engine finding through the review layer'
);
update public.reviewer_notes set body = 'Changed' where id = '33333333-aaaa-4aaa-8aaa-111111111111';
select is(
    (select body from public.reviewer_notes where id = '33333333-aaaa-4aaa-8aaa-111111111111'),
    'Confirm the missing basis.',
    'reviewer notes are append-only'
);
select throws_ok(
    $$update public.follow_up_actions set review_item_id = null where id = '33333333-bbbb-4bbb-8bbb-111111111111'$$,
    '23514', 'follow_up_target_and_creator_are_immutable',
    'follow-up targets cannot be moved after creation'
);

select set_config('request.jwt.claim.sub', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', true);
select is((select count(*) from public.cases where id = '11111111-aaaa-4aaa-8aaa-111111111111'), 0::bigint, 'User B cannot select User A case');
select is((select count(*) from public.formulation_versions where id = '11111111-bbbb-4bbb-8bbb-111111111111'), 0::bigint, 'User B cannot select User A formulation');
select is((select count(*) from public.clarifications where id = '11111111-cccc-4ccc-8ccc-111111111111'), 0::bigint, 'User B cannot select User A clarification');
select is((select count(*) from public.screening_runs where id = '11111111-dddd-4ddd-8ddd-111111111111'), 0::bigint, 'User B cannot select User A screening');
select is((select count(*) from public.review_items where id = '11111111-ffff-4fff-8fff-111111111111'), 0::bigint, 'User B cannot select User A review item');
select is((select count(*) from public.reviewer_notes where id = '33333333-aaaa-4aaa-8aaa-111111111111'), 0::bigint, 'User B cannot select User A reviewer note');
select is((select count(*) from public.follow_up_actions where id = '33333333-bbbb-4bbb-8bbb-111111111111'), 0::bigint, 'User B cannot select User A follow-up');
select is((select count(*) from storage.objects where name like '%/serum.csv'), 0::bigint, 'User B cannot select User A private file');

select set_config('request.jwt.claim.sub', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', true);
update public.screening_runs set result_snapshot = '{"marker":"changed"}'
where id = '11111111-dddd-4ddd-8ddd-111111111111';
select is((select result_snapshot ->> 'marker' from public.screening_runs where id = '11111111-dddd-4ddd-8ddd-111111111111'), 'original', 'screening snapshots cannot be updated');
delete from public.screening_runs where id = '11111111-dddd-4ddd-8ddd-111111111111';
select is((select count(*) from public.screening_runs where id = '11111111-dddd-4ddd-8ddd-111111111111'), 1::bigint, 'screening snapshots cannot be deleted');

select set_config('request.jwt.claim.sub', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', true);
delete from public.cases where id = '11111111-aaaa-4aaa-8aaa-111111111111';
reset role;
select is((select count(*) from public.cases where id = '11111111-aaaa-4aaa-8aaa-111111111111'), 1::bigint, 'User B cannot delete User A case');
select * from finish();
rollback;
