ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS handle text;
ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS account_status text NOT NULL DEFAULT 'active'
    CHECK (account_status IN ('active','suspended','deleted'));
ALTER TABLE team_accounts ADD COLUMN IF NOT EXISTS handle_changed_at timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS team_accounts_handle_unique ON team_accounts (lower(handle));
ALTER TABLE team_accounts ALTER COLUMN handle SET DEFAULT
    ('user_' || left(replace(gen_random_uuid()::text,'-',''),15));
DO $$
DECLARE account text; candidate text; attempt integer;
BEGIN
    FOR account IN SELECT account_id FROM team_accounts WHERE handle IS NULL ORDER BY account_id LOOP
        attempt := 0;
        LOOP
            candidate := 'user_' || left(md5(account || ':' || attempt::text),15);
            IF NOT EXISTS (SELECT 1 FROM team_accounts WHERE lower(handle)=candidate) THEN
                UPDATE team_accounts SET handle=candidate WHERE account_id=account AND handle IS NULL;
                EXIT;
            END IF;
            attempt := attempt + 1;
        END LOOP;
    END LOOP;
END $$;
ALTER TABLE team_accounts ALTER COLUMN handle SET NOT NULL;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='team_accounts'::regclass AND conname='team_accounts_handle_format') THEN
        ALTER TABLE team_accounts ADD CONSTRAINT team_accounts_handle_format
            CHECK (handle ~ '^[a-z0-9][a-z0-9_.]{2,19}$');
    END IF;
END $$;
