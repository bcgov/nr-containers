
import logging
import os
import pathlib
import re
import sys
from logging.config import fileConfig
from typing import Any, Dict, List, Optional, Tuple

import alembic.script.revision
import jproperties
import jproperties
import oracledb
import sqlalchemy
import xxhash

#from alembic.script.revision import ResolutionError, Revision
#alembic.script.revision.ResolutionErrror
from sqlalchemy import text

import alembic

try:
    import flyway_migration_name_validator as flyway_validator
except ImportError:
    from . import flyway_migration_name_validator as flyway_validator

# ------------------------------------------------------------------------------
# Alembic / logging setup
# ------------------------------------------------------------------------------
global config
config = getattr(alembic.context, "config", None)

if config and getattr(config, "config_file_name", None) is not None:
    fileConfig(config.config_file_name)


logger = logging.getLogger("alembic.env")
logger.debug("logger setup complete")


class SQLRevisionInfo:
    """
    Holds information about a single SQL revision, including its version,
    upgrade SQL path, and optional downgrade SQL path.
    """

    def __init__(
        self,
        revision: str,
        upgrade_path: pathlib.Path,
        downgrade_path: Optional[pathlib.Path] = None,
    ):
        self.revision: str = revision
        self.upgrade_path: pathlib.Path = upgrade_path
        self.downgrade_path: Optional[pathlib.Path] = downgrade_path
        self._checksum: Optional[str] = None

    @property
    def checksum(self) -> str:
        if self._checksum is None:
            alembic_utils = AlembicUtils()
            self._checksum = alembic_utils.calc_hash(self.upgrade_path)
        return self._checksum



class MigrationFiles:

    """A class to wrap functionality around discovery of migration files.
    """

    def __init__(self, base_path: pathlib.Path):
        self.base_path = base_path
        self.callbacks_path = self.base_path / "callbacks"
        self.version_re = flyway_validator.VERSIONED_RE
        self.undo_re = flyway_validator.UNDO_RE
        self.repeatable_re = flyway_validator.REPEATABLE_RE
        self.callback_re = flyway_validator.CALLBACK_RE

    def repeatable_sort_key(self, p: pathlib.Path) -> str:
        """a sort function to allow the repeatables to be sorted by only
        the file name and not the subdir/filename

        :param p: incomming path to a repeatable sql file
        :type p: pathlib.Path
        :return: returns the part of the filename after R__ and before .sql,
                    ignoring case, for sorting purposes
        :rtype: str
        """
        name = p.name.lower()
        return name.split("__", 1)[1]

    def validate_repeatable_migrations(self, repeatable_files: List[pathlib.Path]) -> None:
        """Gets a list of the repeatable migrations and raises and error if any
        duplicates based on the repeatable key, which is the part of the filename
        after R__ and before .sql are found

        :param repeatable_files: _description_
        :type repeatable_files: List[pathlib.Path]
        :raises ValueError: Raised when duplicate repeatable migration keys are
            detected, indicating that there are multiple repeatable migration
            files with the same key (i.e., the same name after R__ and before
            .sql).
        """
        seen: Dict[str, pathlib.Path] = {}

        for filepath in repeatable_files:
            key = self.repeatable_key(filepath).lower()
            if key in seen:
                raise ValueError(
                    f"Duplicate repeatable migration key detected: {seen[key]} and {filepath}"
                )
            seen[key] = filepath

    def repeatable_key(self, path: pathlib.Path) -> str:
        """Generate a normalized key for a repeatable migration file.

        extracts the basepath part of the file name and returns a path with
        <object_type/<repeatable_migration_name>

        where object type is something like, VIEWS, TABLES, etc...

        :param path: Path to the repeatable migration file
        :type path: pathlib.Path
        :return: Relative path from base_path with forward slashes
        :rtype: str
        """
        return str(path.relative_to(self.base_path)).replace("\\", "/")

    def validate_undo_migrations(self, migrations: List[SQLRevisionInfo]) -> None:
        """Validate that migrations have corresponding undo scripts.

        Checks if each migration has a downgrade path. Logs a warning if any
        migrations are missing undo scripts, as downgrades will not be possible
        for those revisions.

        :param migrations: List of migration revisions to validate
        :type migrations: List[SQLRevisionInfo]
        """
        missing_undo_count = 0
        for migration in migrations:
            if migration.downgrade_path is None:
                # logger.debug(
                #     "No undo migration found for revision %s (expected U%s__*.sql)",
                #     migration.revision,
                #     migration.revision,
                # )
                missing_undo_count += 1
        if missing_undo_count > 0:
            logger.warning(
                "%s out of %s migrations missing undo scripts. Downgrades not possible for these revisions.",
                missing_undo_count,
                len(migrations),
            )



    def discover_repeatable_migrations(self) -> List[pathlib.Path]:
        if not self.base_path.exists():
            return []

        repeatables = [p for p in sorted(self.base_path.rglob("*.sql")) if self.repeatable_re.match(p.name)]
        # repeatables.sort(key=lambda p: repeatable_key(p).lower())
        repeatables.sort(key=self.repeatable_sort_key)
        return repeatables

    def discover_callback_migrations(self) -> Dict[str, pathlib.Path]:
        """Discover Flyway-style callback scripts under the schema callbacks folder.

        Callback filenames are matched by stem, e.g. afterMigrate.sql.
        """
        if not self.callbacks_path.exists():
            return {}

        callbacks: Dict[str, pathlib.Path] = {}
        for filepath in sorted(self.callbacks_path.glob("*.sql")):
            if not self.callback_re.match(filepath.name):
                continue

            callback_name = filepath.stem
            if callback_name in callbacks:
                raise ValueError(
                    f"Duplicate callback migration for event {callback_name}: {filepath}"
                )
            callbacks[callback_name] = filepath

        return callbacks

    def discover_sql_migrations(self) -> List[SQLRevisionInfo]:
        alembic_utils = AlembicUtils()
        if not self.base_path.exists():
            raise FileNotFoundError(f"Migration directory does not exist: {self.base_path}")

        sql_files = sorted(self.base_path.rglob("*.sql"))

        single_underscore_files = flyway_validator.detect_single_underscore_migrations(sql_files)
        if single_underscore_files:
            file_names = ", ".join(f.name for f in single_underscore_files)
            logger.warning(
                "🙅‍♀️  Found %d migration file(s) with a single '_' separator instead of '__': [%s]. "
                "These files MUST be renamed to use double '__' (e.g. V<ver>__<name>.sql) in order for Alembic to run them.",
                len(single_underscore_files),
                file_names,
            )

        upgrades: Dict[str, pathlib.Path] = {}
        downgrades: Dict[str, pathlib.Path] = {}

        for filepath in sql_files:
            name = filepath.name

            vm = self.version_re.match(name) # type: ignore
            if vm:
                revision = vm.group(1) # type: ignore
                if revision in upgrades:
                    raise ValueError(f"Duplicate upgrade migration for revision {revision}: {filepath}")
                upgrades[revision] = filepath
                continue

            um = self.undo_re.match(name) # type: ignore
            if um:
                revision = um.group(1) # type: ignore
                if revision in downgrades:
                    raise ValueError(f"Duplicate undo migration for revision {revision}: {filepath}")
                downgrades[revision] = filepath

        if not upgrades:
            return []

        ordered_revisions = sorted(upgrades.keys(), key=alembic_utils.version_key)

        migrations: List[SQLRevisionInfo] = []
        for revision in ordered_revisions:
            migrations.append(
                SQLRevisionInfo(
                    revision=revision,
                    upgrade_path=upgrades[revision],
                    downgrade_path=downgrades.get(revision),
                )
            )
        return migrations

class DatabaseConnectivity:
    """a class used to create connections to the database, and also validate
    that the requested connection makes sense.
    """

    def __init__(self):
        self.set_connection_settings_from_env()
        self.validate_env_settings()

        # used to cache the connection
        self.dbconn: sqlalchemy.Connection | None = None
        self.connectable: sqlalchemy.engine.Engine | None = None

    def set_connection_settings_from_env(self) -> None:
        """sets class variables by reading the various ORACLE_* env vars into
        class properties.
        """
        self.ORACLE_USER = os.getenv("ORACLE_USER", "THE").upper().strip()
        self.ORACLE_PASSWORD = os.getenv("ORACLE_PASSWORD", "default")
        self.ORACLE_HOST = os.getenv("ORACLE_HOST", "localhost")
        self.ORACLE_PORT = os.getenv("ORACLE_PORT", "1525")
        self.ORACLE_SERVICE = os.getenv("ORACLE_SERVICE", "DBDOCK_01")
        self.SYS_PASSWORD = os.getenv("ORACLE_SYS_PASSWORD", self.ORACLE_PASSWORD)
        # schema folder is what is populated by the alembic.sh script. Should
        # be the same as ORACLE_USER for msot migrations but for SYS migrations
        # the user can be SYS but the folder is DBA.  Currently that is the only
        # exception.
        self.ORACLE_SCHEMA_FOLDER = os.getenv("ORACLE_SCHEMA_FOLDER", self.ORACLE_USER).upper().strip()

    def get_scripts_folder(self) -> pathlib.Path:
        """Gets the folder to look in for the sql scripts.  This is typically
        the same as the ORACLE_USER but uppercased, except for when connecting
        as SYS where it is DBA.

        :return: the folder to look in for sql scripts, typically same as
                ORACLE_USER but uppercased, except for SYS where it is DBA.
        :rtype: pathlib.Path
        """
        base_dir = pathlib.Path(__file__).resolve().parent.parent
        scripts_dir = base_dir / 'scripts' / self.ORACLE_SCHEMA_FOLDER
        return scripts_dir

    def validate_env_settings(self):
        """Validates the settings provided in the environment that describe what
        database connection to use.  Mostly when the user is set to SYS allows
        us to use a different directory than the name of the connection user to
        find the migrations in.

        :raises RuntimeError: _description_
        :raises RuntimeError: _description_
        """
        #logger.debug("self.ORACLE_USER: %s", self.ORACLE_USER)
        #logger.debug("self.ORACLE_SCHEMA_FOLDER: %s", self.ORACLE_SCHEMA_FOLDER)
        if self.ORACLE_USER == 'SYS' and self.ORACLE_SCHEMA_FOLDER != 'DBA':
            msg = ("You have set the env var ORACLE_USER=SYS but the "
                f"ORACLE_SCHEMA_FOLDER is set to {self.ORACLE_SCHEMA_FOLDER}. "
                "You probably want to set the ORACLE_USER to be the same as "
                "ORACLE_SCHEMA_FOLDER.  Only exception if is where "
                "ORACLE_SCHEMA_FOLDER=DBA then the ORACLE_USER should be set"
                " to SYS"
                )
            raise RuntimeError(msg)
        elif self.ORACLE_USER != self.ORACLE_SCHEMA_FOLDER and self.ORACLE_USER != 'SYS':
            msg = (f'You set the env var ORACLE_USER={self.ORACLE_USER} and ORACLE_SCHEMA_FOLDER='
                   f"{self.ORACLE_SCHEMA_FOLDER}  These two values should be the same "
                   "The only exception is if the ORACLE_SCHEMA_FOLDER='DBA', in "
                   "which case the ORACLE_USER should be set to SYS."
            )
            raise RuntimeError(msg)

        # Todo: delete this parameter and just use ORACLE_USER everywhere, including the wrapper script that sets the env vars.  It is redundant to have both ORACLE_USER and ORACLE_SCHEMA_FOLDER when they are always the same except for the uppercasing, and it just adds confusion.
        #ORACLE_SCRIPT_FOLDER = os.getenv("ORACLE_SCHEMA_FOLDER", ORACLE_USER).upper()
        # when running the sys migrations the location of the alembic versions and
        # repeatables tables is stored in a different schema.  This variable is the
        # one used to refer to the location of that alembic tables.
        #ORACLE_OBJ_SCHEMA = ORACLE_USER.upper()

    def get_sqlalchemy_url(self) -> str:
        """consume the parameters from the environment and use to construct a
        connection string.

        :return: a sqlalchemy url
        :rtype: str
        """
        password = self.ORACLE_PASSWORD
        if self.ORACLE_USER.upper() == 'SYS':
            # when connecting as SYS we need to use the SYS_PASSWORD and not the
            # regular ORACLE_PASSWORD, and we also need to specify that we are
            # connecting as SYSDBA in the connect args, which is handled in the
            # get_connection_engine method.
            password = self.SYS_PASSWORD

        sqlalchemy_url = (
            f"oracle+oracledb://{self.ORACLE_USER}:{password}@"
            f"{self.ORACLE_HOST}:{self.ORACLE_PORT}/?service_name={self.ORACLE_SERVICE}")
        return sqlalchemy_url

    def get_connect_args(self, asDBA: bool=False) -> Dict[str, object]:
        """Get the connection arguments for the database connection.

        :param asDBA: Whether to connect as a DBA user
        :type asDBA: bool
        :return: A dictionary of connection arguments
        :rtype: Dict[str, object]
        """
        # connect_args: dict[str, object] = {
        #     "dsn": f"{self.ORACLE_HOST}:{self.ORACLE_PORT}/?service_name={self.ORACLE_SERVICE}",
        # }
        connect_args: dict[str, object] = {}
        if asDBA:
            connect_args["mode"] = oracledb.AuthMode.SYSDBA  # type: ignore
        return connect_args

    def get_connection_engine(self) -> sqlalchemy.engine.Engine:
        """Using the parmeters extracted from the environment create and return
        a sqlalchemy engine / connectable object.

        :return: _description_
        :rtype: sqlalchemy.engine.Engine
        """
        if self.connectable is None:

            sql_alchemy_url = self.get_sqlalchemy_url()
            redacted_sqlalchemy_url = re.sub(r"(://)([^@]+)(@)", r"\1***\3", sql_alchemy_url)
            logger.debug("SQLAlchemy URL: %s", redacted_sqlalchemy_url)
            if self.ORACLE_USER.upper() == 'SYS':
                logger.debug("connecting as SYS")
                connect_args = self.get_connect_args(asDBA=True)
                logger.debug("connect_args: %s", connect_args)
                self.connectable = sqlalchemy.create_engine(
                    sql_alchemy_url,
                    connect_args=connect_args,
                )
            else:
                connect_args = self.get_connect_args(asDBA=False)
                logger.debug("connect_args: %s", connect_args)
                logger.debug("connecting as a regular user: %s", self.ORACLE_USER)
                self.connectable = sqlalchemy.create_engine(
                    sql_alchemy_url, connect_args=connect_args, poolclass=None, echo=False)
        return self.connectable

    def get_connection(self, connectable: sqlalchemy.engine.Engine | None = None) -> sqlalchemy.engine.Connection:
        """Get a connection from the given connectable (engine).

        :param connectable: The SQLAlchemy engine to get a connection from.
        :type connectable: sqlalchemy.engine.Engine
        :return: A connection object from the engine.
        :rtype: sqlalchemy.engine.Connection
        """
        if not connectable:
            #logger.debug("getting connection engine")
            connectable = self.get_connection_engine()
        if self.dbconn is None:
            self.dbconn = connectable.connect()
            if self.ORACLE_USER.upper() == 'SYS':
                logger.debug("Getting connection as SYS with SYSDBA mode")
                self.dbconn.execute(sqlalchemy.text(f"ALTER SESSION SET CONTAINER={self.ORACLE_SERVICE}"))
        return self.dbconn


SAFE_SCHEMA_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")


def load_flyway_properties(
    schema_name: str,
    config_dir: Optional[pathlib.Path] = None,
) -> Dict[str, str]:
    """Loads a Flyway-compatible .properties file for the given schema from
    the canonical alembic/configs/<schema>.properties directory.

    Returns a dictionary mapping lowercase property keys to stripped string values.
    """
    if not schema_name:
        return {}

    if not SAFE_SCHEMA_PATTERN.match(schema_name):
        logger.warning("Invalid schema name: %r contains unsafe characters", schema_name)
        return {}

    configs_dir = config_dir or (pathlib.Path(__file__).resolve().parent / "configs")
    if not configs_dir.exists():
        logger.debug("Configs directory does not exist: %s", configs_dir)
        return {}

    target_file = configs_dir / f"{schema_name.upper()}.properties"
    if not target_file.exists():
        target_file = configs_dir / f"{schema_name}.properties"

    try:
        if not target_file.resolve().is_relative_to(configs_dir.resolve()):
            logger.warning("Path traversal attempt detected: %s", schema_name)
            return {}
    except (ValueError, RuntimeError):
        return {}

    if not target_file.exists():
        logger.debug("No Flyway properties file found for schema %s at %s", schema_name, target_file)
        return {}

    logger.debug("Loading Flyway properties for %s from %s", schema_name, target_file)
    p = jproperties.Properties()
    with open(target_file, "rb") as f:
        p.load(f, "utf-8")

    properties: Dict[str, str] = {
        k.lower(): v.data.strip().strip("'\"") for k, v in p.items()
    }
    return properties

class AlembicHelpers:
    """A class for Alembicy database opertions such as ensuring the version table
      exists, getting the current version, etc... any communication with the
      database pertaining to alembic operations should go through this class

    Some examples:
    * migration sql is executed from
    * versioning information gets updated

    in a nutshell if it involves an alembicy like operation that needs a database
    connection it gets done here.
    """
    def __init__(
        self,
        dbconct: DatabaseConnectivity,
        flyway_config: Optional[Dict[str, str]] = None,
        config_dir: Optional[pathlib.Path] = None,
    ):
        self.dbconct = dbconct
        self.config_dir = config_dir
        self.repeatable_data_cache: Dict[str, str] = {}
        self.alembic_utils = AlembicUtils()
        self.ignored_ora_codes: set[int] = set()
        if flyway_config is not None:
            self.flyway_config = flyway_config
        else:
            self.flyway_config = self.load_flyway_config()

    def load_flyway_config(self) -> Dict[str, str]:
        """Loads Flyway properties for the active schema or connection user."""
        for schema in [self.dbconct.ORACLE_SCHEMA_FOLDER, self.dbconct.ORACLE_USER]:
            if schema:
                props = load_flyway_properties(schema, config_dir=self.config_dir)
                if props:
                    return props
        return {}

    def execute_sql_migration(self, migration_file_path: pathlib.Path) -> None:
        connection = self.dbconct.get_connection()
        logger.info("Executing %s", migration_file_path)
        sql_text = migration_file_path.read_text(encoding="utf-8")

        prop_placeholders = {}
        for k, v in self.flyway_config.items():
            if k.startswith("flyway.placeholders."):
                prop_placeholders[k[len("flyway.placeholders."):]] = v

        sql_text = self.alembic_utils.substitute_flyway_placeholders(sql_text, extra_placeholders=prop_placeholders)
        statements = self.alembic_utils.split_oracle_statements(sql_text)

        for stmt in statements:
            try:
                connection.exec_driver_sql(stmt)
                # commit after every migration
                connection.commit()
            except sqlalchemy.exc.DBAPIError as e: # type: ignore
                oracle_error = None
                if hasattr(e.orig, "args") and e.orig.args: # type: ignore
                    oracle_error = e.orig.args[0] # type: ignore

                ora_code = getattr(oracle_error, "code", None) # type: ignore
                # oracledb's .message already reads "ORA-nnnnn: <text>"
                ora_message = getattr(oracle_error, "message", None) # type: ignore
                if not ora_message:
                    ora_message = e.orig if e.orig else e
                ora_message = str(ora_message).strip()

                if ora_code in self.ignored_ora_codes:
                    logger.warning("Ignoring Oracle error ORA-%s: %s", ora_code, ora_message)
                    continue

                logger.debug("Failed statement in %s:\n%s", migration_file_path, stmt)
                raise MigrationSQLError(migration_file_path, ora_message) from e

    def run_downgrade_step(self, script: alembic.script.revision.Revision) -> None:
        downgrade_path = getattr(script, "downgrade_path", None)

        if not downgrade_path:
            raise RuntimeError(
                f"No Flyway-style undo migration found for revision {script.revision} "
                f"(expected U{script.revision}__*.sql)"
            )
        self.execute_sql_migration(pathlib.Path(downgrade_path))
        self.remove_applied_revision(script.revision)
        logger.info("Undid revision %s", script.revision)

    def run_upgrade_step(self, script: alembic.script.revision.Revision) -> None:
        """Execute an upgrade migration step for a given revision script.

        Executes the SQL migration file associated with the revision, handles
        container switching for SYS user on Oracle databases, and records the
        applied revision in the version table.

        :param script: The revision script to upgrade
        :type script: alembic.script.revision.Revision
        :raises RuntimeError: If no upgrade SQL file is associated with the revision
        """
        connection = self.dbconct.get_connection()
        upgrade_path = getattr(script, "upgrade_path", None)
        checksum = getattr(script, "checksum", None)

        if not upgrade_path:
            raise RuntimeError(f"No upgrade SQL file associated with revision {script.revision}")

        if self.dbconct.ORACLE_USER.upper() == 'SYS':
            # some of the sys scripts need to run in the context of the CDB,
            # so switching to the PDB after all sys stuff is run
            # before recording the version table changes as that one requires the
            # PDB
            logger.debug("setting session container to DBDOCK_01 for SYS user before upgrade")

            connection.execute(text(f"ALTER SESSION SET CONTAINER={self.dbconct.ORACLE_SERVICE}"))
        self.execute_sql_migration(pathlib.Path(upgrade_path))
        self.record_applied_revision(script.revision, checksum) # type: ignore
        logger.info("Applied revision %s", script.revision)

    def record_applied_revision(self, revision: str, checksum: str) -> None:
        logger.debug("adding revision: %s and checksum: %s to version table", revision, checksum)
        connection = self.dbconct.get_connection()
        version_table = self.get_version_table_name()
        revision_table_schema = self.get_revision_table_schema()
        connection.execute(
            text(
                f"""
                INSERT INTO {revision_table_schema}.{version_table} (version_num, checksum)
                VALUES (:revision, :checksum)
                """
            ),
            {"revision": revision, "checksum": checksum},
        )
        connection.commit()

    def remove_applied_revision(self, revision: str) -> None:
        logger.debug("removing revision: %s from version table", revision)
        connection = self.dbconct.get_connection()
        revision_table_schema = self.get_revision_table_schema()
        version_table = self.get_version_table_name()
        connection.execute(
            text(
                f"""
                DELETE FROM {revision_table_schema}.{version_table}
                WHERE version_num = :revision
                """
            ),
            {"revision": revision},
        )
        connection.commit()
        self.populate_repeatable_cache()

    def stamp_revision(self, revision: str, checksum: str) -> None:
        """Idempotently record or update a revision and its checksum in the version table.

        :param revision: Version identifier (e.g., '16.00096')
        :type revision: str
        :param checksum: Hash of the migration file
        :type checksum: str
        """
        logger.debug("stamping revision: %s with checksum: %s", revision, checksum)
        connection = self.dbconct.get_connection()
        version_table = self.get_version_table_name()
        revision_table_schema = self.get_revision_table_schema()
        connection.execute(
            text(
                f"""
                MERGE INTO {revision_table_schema}.{version_table} t
                USING (
                    SELECT :revision AS version_num,
                           :checksum AS checksum
                    FROM dual
                ) s
                ON (t.version_num = s.version_num)
                WHEN MATCHED THEN
                    UPDATE SET
                        t.checksum = s.checksum,
                        t.installed_on = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN
                    INSERT (version_num, checksum, installed_on)
                    VALUES (s.version_num, s.checksum, CURRENT_TIMESTAMP)
                """
            ),
            {"revision": revision, "checksum": checksum},
        )
        connection.commit()

    def clear_applied_versions(self) -> None:
        """Removes all applied versions from the version table."""
        logger.debug("clearing all applied versions from version table")
        connection = self.dbconct.get_connection()
        revision_table_schema = self.get_revision_table_schema()
        version_table = self.get_version_table_name()
        connection.execute(
            text(f"DELETE FROM {revision_table_schema}.{version_table}")
        )
        connection.commit()

    def get_repeatable_checksum(self, script_name: str) -> Optional[str]:
        """Retrieves the checksum for a repeatable migration script from the cache.

        :param script_name: The name of the repeatable migration script
        :type script_name: str
        :return: The checksum of the script if found, None otherwise
        :rtype: Optional[str]
        """
        self.populate_repeatable_cache()
        if script_name in self.repeatable_data_cache:
            return self.repeatable_data_cache[script_name]
        else:
            return None

    def populate_repeatable_cache(self, refresh:bool=False) -> None:
        """Loads the repeatable migration checksums from the database into the
        in-memory cache.  This is used to avoid unnecessary database queries when
        checking if a repeatable migration has changed.  Individual queries slow the
        process down significantly when there are many repeatable migrations.

        :param connection: The database connection to use.
        :type connection: sqlalchemy.engine.Connection
        :param refresh: If True, forces a reload of the cache from the database.
                        If False, will skip loading if the cache is already
                        populated.
        :type refresh: bool
        """
        if refresh or not self.repeatable_data_cache:
            repeatable_table = self.get_repeatable_table_name()
            revision_table_schema = self.get_revision_table_schema()
            # ensure connection is established before trying to load cache
            connection = self.dbconct.get_connection()
            logger.info("Loading repeatable migration checksums into cache from"
                        " %s.%s", revision_table_schema, repeatable_table)
            rows = connection.execute( # type: ignore
                text(
                    f"""
                    SELECT script_name, checksum
                    FROM {revision_table_schema}.{repeatable_table}
                    """
                )
            ).fetchall()

            for row in rows:
                self.repeatable_data_cache[row[0]] = row[1]

    def get_version_table_name(self) -> str:
        """Gets the name of the table to use for the ALEMBIC versions that have
        been applied to the database, resolved via flyway.table in the schema's
        Flyway properties file.

        :return: the name of the version table to use.
        :rtype: str
        """
        if "flyway.table" in self.flyway_config:
            return self.flyway_config["flyway.table"]
        schema = self.dbconct.ORACLE_SCHEMA_FOLDER or self.dbconct.ORACLE_USER
        return f"{schema}_ALEMBIC_VERSION_SQL"

    def get_repeatable_table_name(self) -> str:
        """Gets the name of the table that keeps track of the repeatable version
        table, resolved via flyway.repeatabletable in the schema's Flyway properties file.

        :return: name of the repeatable table.
        :rtype: str
        """
        if "flyway.repeatabletable" in self.flyway_config:
            return self.flyway_config["flyway.repeatabletable"]
        schema = self.dbconct.ORACLE_SCHEMA_FOLDER or self.dbconct.ORACLE_USER
        return f"{schema}_ALEMBIC_REPEATABLE_SQL"

    def get_revision_table_schema(self) -> str:
        """Gets the schema where the version/repeatable tables are located,
        resolved via flyway.defaultSchema in the schema's Flyway properties file.

        :return: the schema to use for the version table.
        :rtype: str
        """
        if "flyway.defaultschema" in self.flyway_config:
            return self.flyway_config["flyway.defaultschema"]
        return "ALEMBIC"

    def ensure_version_table(self) -> None:
        """Ensures that the version table exists in the database, creating it if
        it does not.
        """
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        VERSION_TABLE = self.get_version_table_name()
        logger.info("checking for a version table in the db (%s)...", ORACLE_OBJ_SCHEMA)
        connection = self.dbconct.get_connection()
        inspector = sqlalchemy.inspect(connection)
        existing_tables = {name.upper() for name in inspector.get_table_names(schema=ORACLE_OBJ_SCHEMA)}
        logger.debug("number of existing tables in schema %s: %s", ORACLE_OBJ_SCHEMA, len(existing_tables))
        if VERSION_TABLE.upper() in existing_tables:
            logger.debug("version table %s already exists!", VERSION_TABLE)
            return

        logger.info("Creating %s.%s", ORACLE_OBJ_SCHEMA, VERSION_TABLE)
        pk_name = f"pk_{ORACLE_OBJ_SCHEMA.lower()}_{VERSION_TABLE.lower()}"
        sql = f"""
                CREATE TABLE {ORACLE_OBJ_SCHEMA}.{VERSION_TABLE} (
                    version_num    VARCHAR2(128) NOT NULL,
                    checksum       VARCHAR2(64)  NOT NULL,
                    installed_on   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    CONSTRAINT {pk_name} PRIMARY KEY (version_num)
                )
                """
        connection.exec_driver_sql(sql)

    def ensure_repeatable_table(self) -> None:
        """Ensures that the repeatable table exists in the database, creating it
          if it does not."""
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        REPEATABLE_TABLE = self.get_repeatable_table_name()
        connection = self.dbconct.get_connection()
        logger.debug("checking for a repeatable table in the db...")


        oracle_service = getattr(self.dbconct, 'ORACLE_SERVICE', None)
        if self.dbconct.ORACLE_USER == 'SYS' and oracle_service:
            if not re.fullmatch(r"[A-Za-z0-9_#$]+", oracle_service):
                raise ValueError(f"Invalid Oracle container name: {oracle_service!r}")
            connection.execute(text(f"ALTER SESSION SET CONTAINER={oracle_service}"))

        inspector = sqlalchemy.inspect(connection)
        existing_tables = {name.upper() for name in inspector.get_table_names(schema=ORACLE_OBJ_SCHEMA)}
        logger.debug("number of existing tables in schema %s: %s", ORACLE_OBJ_SCHEMA, len(existing_tables))
        if REPEATABLE_TABLE.upper() in existing_tables:
            return

        logger.info("Creating %s.%s", ORACLE_OBJ_SCHEMA, REPEATABLE_TABLE)
        pk_name = f"pk_{ORACLE_OBJ_SCHEMA.lower()}_{REPEATABLE_TABLE.lower()}"


        connection.execute(
            text(
                f"""
                CREATE TABLE {ORACLE_OBJ_SCHEMA}.{REPEATABLE_TABLE} (
                    script_name    VARCHAR2(255) NOT NULL,
                    checksum       VARCHAR2(64)  NOT NULL,
                    installed_on   TIMESTAMP     DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    CONSTRAINT {pk_name} PRIMARY KEY (script_name)
                )
                """
            )
        )

    def get_installed_checksum(self, revision: str) -> Optional[str]:
        """Query the version table to retrieve the version checksum for a specific
        version number.

        :param revision: A version number that we want to get the checksum for,
            typically in the format of something like 1.0 or 2.1.3
        :type revision: str
        :return: The checksum for the specified version, or None if the version
            is not found.
        :rtype: Optional[str]
        """
        connection = self.dbconct.get_connection()
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        VERSION_TABLE = self.get_version_table_name()
        row = connection.execute(
            text(
                f"""
                SELECT checksum
                FROM {ORACLE_OBJ_SCHEMA}.{VERSION_TABLE}
                WHERE version_num = :revision
                """
            ),
            {"revision": revision},
        ).fetchone()

        return row[0] if row else None

    def get_applied_versions(self) -> List[str]:
        """Queries the version table and returns a list that has been sorted on
        the version number.

        :return: a list of version numbers that have been applied to the database
        as defined by the version table.
        :rtype: List[str]
        """        """ """
        connection = self.dbconct.get_connection()
        logger.debug("loading the version tables checksums...")
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        VERSION_TABLE = self.get_version_table_name()

        rows = connection.execute(
            text(
                f"""
                SELECT version_num
                FROM {ORACLE_OBJ_SCHEMA}.{VERSION_TABLE}
                """
            )
        ).fetchall()

        return sorted([row[0] for row in rows], key=self.alembic_utils.version_key)

    def get_applied_checksum_map(self) -> Dict[str, str]:
        """Queries the version table in a single SQL call and returns a dictionary
        mapping version_num to checksum.

        :return: Dict mapping version_num -> installed checksum
        :rtype: Dict[str, str]
        """
        connection = self.dbconct.get_connection()
        logger.debug("loading the version table checksums...")
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        VERSION_TABLE = self.get_version_table_name()

        rows = connection.execute(
            text(
                f"""
                SELECT version_num, checksum
                FROM {ORACLE_OBJ_SCHEMA}.{VERSION_TABLE}
                """
            )
        ).fetchall()

        return {row[0]: row[1] for row in rows if row[0]}

    def validate_checksums(self, script_dir: alembic.script.base.ScriptDirectory) -> None:
        """Validates all applied versioned migrations recorded in the database against the local scripts on disk.

        Scans the entire set of applied revisions in the database, verifying that:
        1. Every applied revision exists in the local ScriptDirectory.
        2. The installed database checksum matches the current file checksum on disk.

        Aggregates all missing revisions and checksum mismatches encountered across the entire
        migration history and reports them together in a single error message before failing.

        :param script_dir: Alembic ScriptDirectory containing local migration scripts.
        :type script_dir: alembic.script.base.ScriptDirectory
        :raises RuntimeError: If any applied revision is missing locally or if any checksum mismatch is detected.
        """
        logger.info("Validating the V migration checksums...")
        checksum_map = self.get_applied_checksum_map()

        missing_revisions: List[str] = []
        mismatched_checksums: List[str] = []

        for revision, installed_checksum in checksum_map.items():
            try:
                script = script_dir.get_revision(revision)
            except alembic.script.revision.ResolutionError:
                missing_revisions.append(revision)
                continue

            if not script:
                missing_revisions.append(revision)
                continue

            current_checksum = getattr(script, "checksum", None)

            if installed_checksum and current_checksum and installed_checksum != current_checksum:
                upgrade_path = getattr(script, "upgrade_path", None)
                if upgrade_path:
                    file_info = f"{upgrade_path.name} ({upgrade_path})"
                elif getattr(script, "path", None):
                    file_info = f"{pathlib.Path(script.path).name} ({script.path})"
                else:
                    file_info = str(script)

                mismatched_checksums.append(
                    f"  - File: {file_info}\n"
                    f"    Revision:          {revision}\n"
                    f"    Database checksum: {installed_checksum}\n"
                    f"    Disk checksum:     {current_checksum}"
                )

        errors: List[str] = []
        if missing_revisions:
            errors.append(
                f"Found {len(missing_revisions)} applied revision(s) recorded in the database that are missing locally on disk:\n"
                + "\n".join(f"  - Revision {rev}" for rev in missing_revisions)
            )
        if mismatched_checksums:
            errors.append(
                f"Found {len(mismatched_checksums)} checksum mismatch(es) (previously applied migration files appear to have been modified):\n"
                + "\n".join(mismatched_checksums)
            )

        if errors:
            raise RuntimeError(
                "Migration checksum validation failed:\n\n" + "\n\n".join(errors)
            )


    def get_current_revision(self) -> Optional[str]:
        """Get the current revision applied to the database.

        Returns the most recently applied migration revision, or None if no
        revisions have been applied yet.

        :return: The current revision identifier, or None if no revisions applied
        :rtype: Optional[str]
        """
        applied = self.get_applied_versions()
        logger.debug("applied revisions: %s", applied[-1] if applied else None)
        return applied[-1] if applied else None

    def record_repeatable_checksum(self, script_name: str, checksum: str) -> None:
        """Records the checksum for a repeatable migration script.

        :param script_name: The name of the repeatable migration script
        :type script_name: str
        :param checksum: The checksum of the script
        :type checksum: str
        """
        connection = self.dbconct.get_connection()
        ORACLE_OBJ_SCHEMA = self.get_revision_table_schema()
        REPEATABLE_TABLE = self.get_repeatable_table_name()

        self.ensure_repeatable_table()

        connection.execute(
            text(
                f"""
                MERGE INTO {ORACLE_OBJ_SCHEMA}.{REPEATABLE_TABLE} t
                USING (
                    SELECT :script_name AS script_name,
                        :checksum AS checksum
                    FROM dual
                ) s
                ON (t.script_name = s.script_name)
                WHEN MATCHED THEN
                    UPDATE SET
                        t.checksum = s.checksum,
                        t.installed_on = CURRENT_TIMESTAMP
                WHEN NOT MATCHED THEN
                    INSERT (script_name, checksum, installed_on)
                    VALUES (s.script_name, s.checksum, CURRENT_TIMESTAMP)
                """
            ),
            {"script_name": script_name, "checksum": checksum},
        )
        connection.commit()
        # make sure the change is saved to the cached data.
        self.repeatable_data_cache[script_name] = checksum

class RevisionManagement:
    def __init__(self,
                    migrations: List[SQLRevisionInfo]):
        self.script_dir: alembic.script.base.ScriptDirectory = getattr(alembic.context, "script", None)
        self.migrations = migrations

    def populate_revision_graph(self) -> None:
        """Builds the revision graph for each migration, defining the script
        to run for an upgrade, and the corresponding script for downgrade, as
        well as populating the checksum property.
        """
        logger.info("Loading revision graph for %s migrations", len(self.migrations))
        if getattr(self.script_dir, "_sql_graph_loaded", False):
            return

        previous_revision: Optional[str] = None

        for migration in self.migrations:
            rev = alembic.script.revision.Revision(
                revision=migration.revision,
                down_revision=previous_revision,
            )
            rev.upgrade_path = migration.upgrade_path # type: ignore
            rev.downgrade_path = migration.downgrade_path # type: ignore
            rev.checksum = migration.checksum # type: ignore

            self.script_dir.revision_map.add_revision(rev)
            previous_revision = migration.revision

        self.script_dir._sql_graph_loaded = True  # type: ignore


    def get_requested_revision(self) -> Optional[str]:
        """Extracts the requested revision argument from the CLI call to alembic.

        This method retrieves the target revision specified by the user when
        invoking an alembic command (e.g., 'alembic upgrade 7.00343'). The
        revision argument is stripped of leading/trailing whitespace. If no
        revision was provided or if a KeyError occurs during retrieval, None
        is returned.

        :return: The target revision string, or None if not provided or on error
        :rtype: Optional[str]
        """
        try:
            requested_revision = alembic.context.get_revision_argument()
            requested_revision = requested_revision.strip() if requested_revision else None # type: ignore
            return requested_revision # type: ignore
        except KeyError:
            return None

class AlembicUtils:
    """stuff that I don't know where else to put

    """
    def __init__(self):
        pass

    def get_alembic_verb(self) -> Optional[str]:
        """gets the verb that was used in the alembic command, such as "upgrade",
        "downgrade", "stamp", or "repair".
        """
        try:
            x_args = alembic.context.get_x_argument(as_dictionary=True)
            if "verb" in x_args:
                return x_args["verb"].lower()
            if x_args.get("repair") in ("true", "1", "True"):
                return "repair"
        except Exception:
            pass

        if os.getenv("ALEMBIC_VERB"):
            return os.getenv("ALEMBIC_VERB").lower()

        cmd_name = getattr(getattr(getattr(alembic.context.config,
                                                "cmd_opts",
                                                None),
                                        "cmd", (None,))[0],
                                        "__name__",
                                        None)
        cmd_name = cmd_name.lower() if cmd_name else None
        return cmd_name

    def validate_verb(self) -> bool:
        """Validates that the verb used in the alembic command is one of the
        supported verbs, such as "upgrade", "downgrade", "current", "stamp", "baseline", or "repair".

        :raises ValueError: If the verb is not supported.
        """
        verb = self.get_alembic_verb()
        valid_verbs = {"upgrade", "downgrade", "current", "stamp", "baseline", "repair"}
        if verb not in valid_verbs:
            raise ValueError(f"Unsupported alembic command verb: {verb}. "
                             f"Supported verbs are: {valid_verbs}")
        logger.debug("alembic command verb: %s", verb)
        return True

    def is_dry_run(self) -> bool:
        """Determines if the migration should be run in dry-run mode.
        Checks for:
        - Alembic -x argument (dry_run=true, dry-run=true, dryrun=true, or valueless key)
        - Environment variables ALEMBIC_DRY_RUN or DRY_RUN
        - cmd_opts flag if present
        """
        try:
            x_args = alembic.context.get_x_argument(as_dictionary=True)
            for key in ("dry_run", "dry-run", "dryrun"):
                if key in x_args:
                    val = x_args[key]
                    if val is None or str(val).lower() in ("", "true", "1", "yes", "y"):
                        return True
        except Exception:
            pass

        if os.getenv("ALEMBIC_DRY_RUN", "").lower() in ("1", "true", "yes") or \
           os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"):
            return True

        cmd_opts = getattr(getattr(alembic.context, "config", None), "cmd_opts", None)
        if cmd_opts and getattr(cmd_opts, "dry_run", False):
            return True

        return False

    def substitute_flyway_placeholders(
        self,
        sql_text: str,
        extra_placeholders: Optional[Dict[str, str]] = None,
    ) -> str:
        """Substitutes Flyway-style ${placeholder} tokens in SQL text using
        environment variables prefixed with FLYWAY_PLACEHOLDERS_ or extra placeholders.

        For example, env var FLYWAY_PLACEHOLDERS_THE_PASSWORD=secret will
        replace all occurrences of ${THE_PASSWORD} in the SQL.

        :param sql_text: The SQL text to perform substitutions on.
        :type sql_text: str
        :param extra_placeholders: Optional dictionary of additional placeholders.
        :type extra_placeholders: Optional[Dict[str, str]]
        :return: The SQL text with placeholders substituted.
        :rtype: str
        """
        prefix = "FLYWAY_PLACEHOLDERS_"
        placeholders = {
            key[len(prefix):]: value
            for key, value in os.environ.items()
            if key.startswith(prefix)
        }
        if extra_placeholders:
            placeholders.update(extra_placeholders)
        if placeholders:
            logger.debug("Substituting %d Flyway placeholder(s): %s", len(placeholders), list(placeholders.keys()))
        for key, value in placeholders.items():
            sql_text = sql_text.replace(f"${{{key}}}", value)
        return sql_text

    def strip_line_comment(self, line: str) -> str:
        """Removes any commented out lines from a SQL line.

        :param line: The line of SQL to process.
        :type line: str
        :return: The line without any SQL comments.
        :rtype: str
        """
        return re.sub(r"--.*$", "", line)


    def version_key(self, revision: str) -> Tuple[int, ...]:
        """turns a dotted revision string into a tuple of integers so version
        comparisons are numeric, not string-based.

        :param revision: a revision string such as "1.0" or "2.1.3"
        :return: a tuple of integers representing the revision that can be safely
            sorted.
        :rtype: Tuple[int, ...]
        """
        return tuple(int(part) for part in revision.split("."))

    _hash_cache: Dict[str, Tuple[float, int, str]] = {}

    def calc_hash(self, path: pathlib.Path) -> str:
        """Calculates the XXHash128 hash of a file, using in-memory mtime/size caching.

        :param path: The path to the file to hash.
        :type path: pathlib.Path
        :return: The hexadecimal hash digest of the file.
        :rtype: str
        """
        try:
            stat = path.stat()
            cache_key = str(path)
            cached = AlembicUtils._hash_cache.get(cache_key)
            if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                return cached[2]

            h = xxhash.xxh128()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            digest = h.hexdigest()
            AlembicUtils._hash_cache[cache_key] = (stat.st_mtime, stat.st_size, digest)
            return digest
        except Exception:
            h = xxhash.xxh128()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()


    def split_oracle_statements(self, sql_text: str) -> List[str]:
        """
        Split Oracle SQL script into executable statements.

        Handles:
        - regular SQL statements ending in ;
        - PL/SQL / DDL objects terminated by a line containing only /
        - CREATE [OR REPLACE] [NON]EDITIONABLE PACKAGE / TYPE / FUNCTION / PROCEDURE / TRIGGER
        """
        sql_text = sql_text.replace("\r\n", "\n").replace("\r", "\n")

        statements: List[str] = []
        buffer: List[str] = []
        in_block = False

        block_start_patterns = [
            r"^\s*DECLARE\b",
            r"^\s*BEGIN\b",
            r"^\s*CREATE\s+(OR\s+REPLACE\s+)?(?:(?:NON)?EDITIONABLE\s+)?"
            r"(PACKAGE\s+BODY|PACKAGE|FUNCTION|PROCEDURE|TRIGGER|TYPE\s+BODY|TYPE)\b",
        ]

        for line in sql_text.split("\n"):
            stripped = line.strip()
            stripped_no_comment = self.strip_line_comment(line).strip()

            if stripped == "/":
                if buffer:
                    statements.append("\n".join(buffer).strip())
                    buffer = []
                in_block = False
                continue

            if any(re.match(p, stripped, re.IGNORECASE) for p in block_start_patterns):
                in_block = True

            buffer.append(line)

            if not in_block and stripped_no_comment.endswith(";"):
                statements.append("\n".join(buffer).strip().rstrip(";"))
                buffer = []

        if buffer:
            statements.append("\n".join(buffer).strip())

        return [stmt for stmt in statements if stmt]

class AlembicMigrations:
    """This is the class that ties the room together.

    Most operations are completed by this class.

    """
    def __init__(self):
        self.db_conn = DatabaseConnectivity()
        self.alembic_utils = AlembicUtils()
        self.migration = MigrationFiles(self.db_conn.get_scripts_folder())
        self.versioned_migration_file_list = self.migration.discover_sql_migrations()
        self.repeatable_migration_file_list = self.migration.discover_repeatable_migrations()
        self.callback_migration_files = self.migration.discover_callback_migrations()
        self.revision_management: RevisionManagement = \
            RevisionManagement(self.versioned_migration_file_list)
        self.alembic_helpers = AlembicHelpers(self.db_conn)

    def main(self) -> None:
        """
        Run the migrations requested
        """
        self.config_alembic_context()

        self.alembic_utils.validate_verb()

        self.migration.validate_repeatable_migrations(self.repeatable_migration_file_list)
        self.migration.validate_undo_migrations(self.versioned_migration_file_list)

        self.revision_management.populate_revision_graph()

        self.alembic_helpers.ensure_version_table()
        self.alembic_helpers.ensure_repeatable_table()

        verb = self.alembic_utils.get_alembic_verb()
        if verb not in {"stamp", "baseline", "repair"}:
            if self.alembic_utils.is_dry_run():
                try:
                    self.alembic_helpers.validate_checksums(alembic.context.script)
                except RuntimeError as e:
                    logger.warning("Checksum validation issue during dry run: %s", e)
                    print(f"⚠️  [DRY RUN WARNING] Checksum validation issue: {e}")
            else:
                self.alembic_helpers.validate_checksums(alembic.context.script)

        if self.proceed_with_migration():
            logger.info("Proceeding with migration...")
            target_revision = self.resolve_target_revision()
            logger.debug("target revision: %s", target_revision)

            if self.alembic_utils.is_dry_run():
                self.run_dry_run(verb, target_revision)
                return

            if target_revision or verb in {"stamp", "baseline", "repair"} or verb == "downgrade":
                logger.info("Resolved target: %s", target_revision or "base")

                if verb == "upgrade":
                    self.run_callback("beforeMigrate")
                    self.run_upgrade(target_revision)
                    #connection.commit()
                    # now check for repeatables to run after the upgrade, as those might be needed to get the database to a consistent state after the upgrade scripts have run.  For example, if there is a repeatable that creates a view on top of a table that was created in the upgrade, then we need to run that repeatable after the upgrade in order for the view to be created.
                    self.run_repeatables()
                    self.run_callback("afterMigrate")
                elif verb == "downgrade":
                    self.run_downgrade(target_revision)
                    #connection.commit()
                elif verb in {"stamp", "baseline"}:
                    self.run_stamp(target_revision)
                elif verb == "repair":
                    self.run_repair()

    def run_dry_run(self, verb: str, target_revision: Optional[str]) -> None:
        """
        Executes a dry run for upgrade or downgrade operations.
        Does NOT execute any DDL/DML, run callbacks against the DB, or modify
        ALEMBIC_VERSION_SQL / ALEMBIC_REPEATABLE_SQL tracking tables.
        Prints a full, untruncated summary of all files that would be executed.
        """
        current_revision = self.alembic_helpers.get_current_revision()
        current_file = self.get_migration_filename(current_revision)
        current_str = f"{current_revision} - {current_file}" if current_revision and current_file else (current_revision or "None (empty database)")

        repo_root = pathlib.Path(__file__).resolve().parent.parent

        def display_path(p: Optional[pathlib.Path], item: Dict[str, Any]) -> str:
            if p is None:
                desc = item.get("desc")
                desc_str = f" ({desc})" if desc else ""
                return f"[MISSING ON DISK] Expected {item['name']}{desc_str}"
            try:
                rel = str(p.resolve().relative_to(repo_root))
            except Exception:
                rel = str(p)
            desc = item.get("desc")
            if desc and desc != item.get("name"):
                return f"{rel} ({desc})"
            return rel

        target_display = target_revision or "base"
        print("\n" + "-" * 80)
        print("🔍 Alembic Migration Dry Run (no changes applied)")
        print("-" * 80)
        print(f"Command:          {verb}")
        print(f"Current revision: {current_str}")
        print(f"Target revision:  {target_display}")
        print("-" * 80)

        files_to_run: List[Dict[str, Any]] = []
        missing_undo_count = 0
        skipped_repeatables = 0

        if verb == "upgrade":
            # 1. beforeMigrate callback
            bm = self.callback_migration_files.get("beforeMigrate")
            if bm:
                files_to_run.append({
                    "category": "callback",
                    "name": bm.name,
                    "path": bm,
                    "desc": "beforeMigrate callback",
                })

            # 2. Versioned upgrade migrations
            upgrade_migrations = self.get_revisions_to_upgrade(target_revision=target_revision)
            before_each = self.callback_migration_files.get("beforeEachMigrate")
            after_each = self.callback_migration_files.get("afterEachMigrate")

            for migration in upgrade_migrations:
                if before_each:
                    files_to_run.append({
                        "category": "callback",
                        "name": before_each.name,
                        "path": before_each,
                        "desc": f"beforeEachMigrate (for V{migration.revision})",
                    })
                files_to_run.append({
                    "category": "versioned",
                    "name": migration.upgrade_path.name,
                    "path": migration.upgrade_path,
                    "desc": f"V{migration.revision}",
                })
                if after_each:
                    files_to_run.append({
                        "category": "callback",
                        "name": after_each.name,
                        "path": after_each,
                        "desc": f"afterEachMigrate (for V{migration.revision})",
                    })

            # 3. Repeatables that changed or are new
            for filepath in self.repeatable_migration_file_list:
                script_name = self.migration.repeatable_key(filepath)
                checksum = self.alembic_utils.calc_hash(filepath)
                installed_checksum = self.alembic_helpers.get_repeatable_checksum(script_name)

                if installed_checksum == checksum:
                    skipped_repeatables += 1
                    continue

                status_label = "new" if installed_checksum is None else "modified"
                files_to_run.append({
                    "category": "repeatable",
                    "name": filepath.name,
                    "path": filepath,
                    "desc": f"R__{script_name} ({status_label})",
                })

            # 4. afterMigrate callback
            am = self.callback_migration_files.get("afterMigrate")
            if am:
                files_to_run.append({
                    "category": "callback",
                    "name": am.name,
                    "path": am,
                    "desc": "afterMigrate callback",
                })

        elif verb == "downgrade":
            downgrade_migrations = self.get_revisions_to_downgrade(target_revision=target_revision)
            for migration in downgrade_migrations:
                if migration.downgrade_path:
                    files_to_run.append({
                        "category": "undo",
                        "name": migration.downgrade_path.name,
                        "path": migration.downgrade_path,
                        "desc": f"U{migration.revision}",
                    })
                else:
                    missing_undo_count += 1
                    files_to_run.append({
                        "category": "undo",
                        "name": f"U{migration.revision}__*.sql",
                        "path": None,
                        "desc": f"U{migration.revision} [MISSING UNDO SCRIPT]",
                    })
        else:
            print(f"ℹ Dry run not supported for command '{verb}'.")
            return

        if not files_to_run:
            if verb == "upgrade":
                print("\n✓ No migration files would be executed. Database is already up to date.")
            elif verb == "downgrade":
                print("\n✓ No downgrade migration files would be executed.")
        else:
            print(f"\nMigration files that would be executed ({len(files_to_run)} total, in execution order):")
            for i, item in enumerate(files_to_run, 1):
                cat_tag = f"[{item['category']}]".ljust(13)
                p_str = display_path(item['path'], item)
                print(f"  {i:3d}. {cat_tag} {p_str}")

        v_count = sum(1 for f in files_to_run if f["category"] == "versioned")
        r_count = sum(1 for f in files_to_run if f["category"] == "repeatable")
        c_count = sum(1 for f in files_to_run if f["category"] == "callback")
        u_count = sum(1 for f in files_to_run if f["category"] == "undo")

        breakdown = []
        if v_count:
            breakdown.append(f"{v_count} versioned")
        if r_count:
            breakdown.append(f"{r_count} repeatable")
        if c_count:
            breakdown.append(f"{c_count} callback")
        if u_count:
            breakdown.append(f"{u_count} undo")

        summary_suffix = f" ({', '.join(breakdown)})" if breakdown else ""
        print(f"\nSummary: {len(files_to_run)} file(s) would be executed{summary_suffix}.")

        if verb == "upgrade" and self.repeatable_migration_file_list:
            if skipped_repeatables > 0:
                print(f"ℹ  Skipped {skipped_repeatables} unchanged repeatable migration(s).")

        if missing_undo_count > 0:
            print(f"⚠️  WARNING: {missing_undo_count} migration(s) missing undo scripts on disk!")

        print("-" * 80 + "\n")

    def run_repair(self) -> None:
        """
        Repairs migration metadata in the database:
        1. Realigns checksums for all applied versioned migrations in ALEMBIC_VERSION_SQL
           with the calculated checksums of the scripts currently on disk.
        2. Realigns checksums for all recorded repeatable migrations in ALEMBIC_REPEATABLE_SQL
           with the calculated checksums of the scripts currently on disk.
        Logs each repaired checksum and outputs a summary.
        """
        logger.info("🔧 Starting migration metadata repair...")
        checksum_map = self.alembic_helpers.get_applied_checksum_map()
        disk_version_map = {m.revision: m for m in self.versioned_migration_file_list}

        version_repaired = 0
        version_unchanged = 0
        version_missing = 0

        for revision, installed_checksum in checksum_map.items():
            if revision not in disk_version_map:
                logger.warning("⚠️  Applied revision '%s' recorded in DB is missing on disk; cannot repair checksum.", revision)
                print(f"⚠️  Applied revision '{revision}' recorded in DB is missing on disk; skipped.")
                version_missing += 1
                continue

            migration = disk_version_map[revision]
            current_checksum = migration.checksum

            if installed_checksum != current_checksum:
                self.alembic_helpers.stamp_revision(revision, current_checksum)
                logger.info(
                    "🔧 Repaired checksum for versioned migration %s (%s): %s -> %s",
                    revision,
                    migration.upgrade_path.name,
                    installed_checksum,
                    current_checksum,
                )
                print(f"🔧 Repaired V{revision} ({migration.upgrade_path.name}): {installed_checksum} -> {current_checksum}")
                version_repaired += 1
            else:
                version_unchanged += 1

        # Repeatable repair
        repeatable_repaired = 0
        repeatable_unchanged = 0
        for filepath in self.repeatable_migration_file_list:
            script_name = self.migration.repeatable_key(filepath)
            installed_checksum = self.alembic_helpers.get_repeatable_checksum(script_name)
            current_checksum = self.alembic_utils.calc_hash(filepath)

            if installed_checksum is not None:
                if installed_checksum != current_checksum:
                    self.alembic_helpers.record_repeatable_checksum(script_name, current_checksum)
                    logger.info(
                        "🔧 Repaired checksum for repeatable migration %s: %s -> %s",
                        script_name,
                        installed_checksum,
                        current_checksum,
                    )
                    print(f"🔧 Repaired R__{script_name}: {installed_checksum} -> {current_checksum}")
                    repeatable_repaired += 1
                else:
                    repeatable_unchanged += 1

        summary = (
            f"✓ Repair complete: {version_repaired} versioned checksum(s) repaired ({version_unchanged} unchanged"
            + (f", {version_missing} missing" if version_missing else "")
            + f"), {repeatable_repaired} repeatable checksum(s) repaired ({repeatable_unchanged} unchanged)."
        )
        print(summary)
        logger.info(summary)

    def run_callback(self, event_name: str) -> bool:
        """Execute a Flyway-style callback script when present."""
        callback_path = self.callback_migration_files.get(event_name)
        if callback_path is None:
            logger.debug("No callback migration defined for event %s", event_name)
            return False

        logger.info("Running callback %s from %s", event_name, callback_path)
        self.alembic_helpers.execute_sql_migration(callback_path)
        return True

    def run_repeatables(self) -> int:
        """
        Execute repeatable migrations that have changed since last run.

        Iterates through all repeatable migration files, compares their checksums
        with stored values, and applies any that have changed. Logs the number
        of migrations applied and skipped.

        Returns:
            int: Number of repeatable migrations that were applied.
        """
        applied_count = 0
        not_run_rep = 0

        for filepath in self.repeatable_migration_file_list:
            script_name = self.migration.repeatable_key(filepath)
            checksum = self.alembic_utils.calc_hash(filepath)
            installed_checksum = self.alembic_helpers.get_repeatable_checksum(script_name)

            if installed_checksum == checksum:
                #logger.debug("Repeatable unchanged, skipping %s", script_name)
                not_run_rep += 1
                continue

            logger.info("Applying repeatable migration %s", script_name)
            self.alembic_helpers.execute_sql_migration(filepath)
            self.alembic_helpers.record_repeatable_checksum(script_name, checksum)
            applied_count += 1
        if not_run_rep:
            logger.info("Skipped %s unchanged repeatable migrations of %s",
                        not_run_rep,
                        len(self.repeatable_migration_file_list))

        return applied_count

    def run_stamp(self, target_revision: Optional[str]) -> None:
        """
        Stamp / baseline the database to the target revision without running migration scripts.

        Records all migrations up to and including the target revision in the version table
        with their calculated file checksums. Also records current repeatable migration checksums.
        If target_revision is None (i.e. 'base'), all recorded versions are cleared.

        :param target_revision: Target revision identifier, or None for base.
        :type target_revision: Optional[str]
        """
        if target_revision is None:
            logger.info("Stamping database to base (clearing all recorded versions)")
            self.alembic_helpers.clear_applied_versions()
            logger.info("Cleared all recorded versions from version table")
            return

        stamped_count = 0
        target_key = self.alembic_utils.version_key(target_revision)
        for migration in self.versioned_migration_file_list:
            if self.alembic_utils.version_key(migration.revision) <= target_key:
                self.alembic_helpers.stamp_revision(migration.revision, migration.checksum)
                stamped_count += 1

        # Also record current repeatable checksums in repeatable table
        repeatable_stamped = 0
        for filepath in self.repeatable_migration_file_list:
            script_name = self.migration.repeatable_key(filepath)
            checksum = self.alembic_utils.calc_hash(filepath)
            self.alembic_helpers.record_repeatable_checksum(script_name, checksum)
            repeatable_stamped += 1

        logger.info(
            "Baselined database to %s (%d versioned migrations, %d repeatables recorded)",
            target_revision,
            stamped_count,
            repeatable_stamped,
        )

    def run_downgrade(self, target_revision: str):
        """
        Execute downgrade migrations to reach the target revision.

        Retrieves all migrations that need to be downgraded from the current
        revision to the target revision and executes them in reverse order.
        Logs a message if no downgrade migrations need to be applied.

        Args:
            target_revision (str): The target revision to downgrade to.
        """
        downgrade_migrations = self.get_revisions_to_downgrade(
            target_revision=target_revision
        )

        if not downgrade_migrations:
            logger.info("No downgrade migrations to apply")
        else:
            for migration in downgrade_migrations:
                script = alembic.context.script.get_revision(migration.revision)
                self.alembic_helpers.run_downgrade_step(script)

    def run_upgrade(self, target_revision: str) -> None:
        """
        Execute upgrade migrations to reach the target revision.

        Retrieves all migrations that need to be upgraded from the current
        revision to the target revision and executes them in order.
        Logs a message if no upgrade migrations need to be applied.

        :param target_revision: The target revision to upgrade to.
        :type target_revision: str
        """
        with alembic.context.begin_transaction():
            logger.debug("target revision: %s", target_revision)
            upgrade_migrations = self.get_revisions_to_upgrade(
                target_revision=target_revision,
            )
            logger.debug("upgrade_migrations: %s", [m.revision for m in upgrade_migrations])
            if not upgrade_migrations:
                logger.info("No versioned upgrade migrations to apply")
            else:
                for migration in upgrade_migrations:
                    logger.debug("upgrading version: %s", migration.revision)
                    self.run_callback("beforeEachMigrate")
                    script: alembic.script.revision.Revision = \
                        alembic.context.script.get_revision(migration.revision)
                    self.alembic_helpers.run_upgrade_step(script) # type: ignore
                    self.run_callback("afterEachMigrate")

    def get_revisions_to_downgrade(
            self, target_revision: Optional[str]) -> List[SQLRevisionInfo]:
        """
        Retrieve all migrations that need to be downgraded to reach the target revision.

        Determines which migration revisions should be downgraded by comparing the
        current revision with the target revision. Returns an empty list if no current
        revision is set. If no target revision is specified, returns all migrations
        that need to be downgraded to reach base.

        :param target_revision: The target revision to downgrade to.
            If None, downgrades all the way to base.
        :type target_revision: Optional[str]
        :return: List of migration revisions to downgrade, in order.
        :rtype: List[SQLRevisionInfo]
        """
        current_revision = self.alembic_helpers.get_current_revision() # type: ignore

        # Need to know where we are starting from in order to be able to perform
        # a downgrade, otherwise no frame of reference with respect to which
        # migration downgrades need to run.
        if current_revision is None:
            return []


        result: List[SQLRevisionInfo] = []
        for migration in reversed(self.versioned_migration_file_list):
            if self.alembic_utils.version_key(migration.revision) > self.alembic_utils.version_key(current_revision):
                continue
            # if there is no target the assumption is to downgrade all the way
            # back to base, so any migration that is less than or equal to the
            # current revision should be included.  If there is a target revision
            # then only include migrations that are greater than the target
            # revision, as those are the ones we need to downgrade.
            if target_revision is None or self.alembic_utils.version_key(migration.revision) > self.alembic_utils.version_key(target_revision):
                result.append(migration)
        return result

    def get_revisions_to_upgrade(
        self,
        target_revision: Optional[str],
    ) -> List[SQLRevisionInfo]:
        """
        Retrieve all migrations that need to be upgraded to reach the target revision.

        :param target_revision: The target revision to upgrade to.
        :type target_revision: Optional[str]
        :return: List of migration revisions to upgrade, in order.
        :rtype: List[SQLRevisionInfo]
        """
        # need to know the target as that tells the upgrade process where to go
        # for an upgrade.
        if target_revision is None:
            return []

        current_revision = self.alembic_helpers.get_current_revision() # type: ignore
        logger.debug("current revision: %s", current_revision)

        result: List[SQLRevisionInfo] = []
        for migration in self.versioned_migration_file_list: # type: ignore
            if current_revision is not None and \
                    self.alembic_utils.version_key(migration.revision) <= self.alembic_utils.version_key(current_revision):  # type: ignore
                continue
            if self.alembic_utils.version_key(migration.revision) <= self.alembic_utils.version_key(target_revision): # type: ignore
                result.append(migration) # type: ignore
        return result

    def resolve_target_revision(
            self,
    ) -> Optional[str]:
        """
        Resolve the target revision based on the requested revision.

        Supports multiple revision specification formats:
        - "head": The latest revision
        - "base": The base (no migrations)
        - Relative syntax: "+N" or "-N" for N steps forward/backward
        - Explicit revision: A specific revision identifier

        :return: The resolved target revision identifier, or None for base.
        :rtype: Optional[str]
        """
        requested_revision = self.revision_management.get_requested_revision()
        current_revision = self.alembic_helpers.get_current_revision()
        if requested_revision is None:
            return None


        # head
        if requested_revision == "head":
            return alembic.context.script.get_current_head()

        # base
        if requested_revision == "base":
            return None

        # relative revision syntax (+N / -N)
        m = re.fullmatch(r"([+-])(\d+)", requested_revision)
        if m:
            direction = m.group(1)
            steps = int(m.group(2))

            ordered = [m.revision for m in self.versioned_migration_file_list]

            # empty DB case
            if current_revision is None:
                if direction == "+":
                    if steps <= len(ordered):
                        return ordered[steps - 1]
                    return ordered[-1] if ordered else None
                else:
                    return None

            try:
                idx = ordered.index(current_revision)
            except ValueError:
                raise RuntimeError(
                    f"Current revision {current_revision} not found in migrations"
                )

            if direction == "+":
                new_idx = min(idx + steps, len(ordered) - 1)
                return ordered[new_idx]

            else:
                new_idx = idx - steps
                if new_idx < 0:
                    return None
                return ordered[new_idx]

        # explicit revision
        try:
            logger.debug("revision_arg: %s", requested_revision)
            rev = alembic.context.script.get_revision(requested_revision)
            return rev.revision
        except alembic.script.revision.ResolutionError:
            logger.info("No Revisions exist for: %s", requested_revision)
            return None
        except Exception as e:
            logger.error(e)
            # sys.exit()
            raise ValueError(
                f"Unsupported revision target '{requested_revision}'. "
                "Supported: head, base, +N, -N, or explicit revision id."
            )

    def get_migration_filename(self, revision: Optional[str]) -> Optional[str]:
        """Find the migration SQL filename corresponding to a revision string.

        :param revision: Revision version string
        :type revision: Optional[str]
        :return: Filename of the migration SQL file, or None if not found
        :rtype: Optional[str]
        """
        if not revision:
            return None
        for m in self.versioned_migration_file_list:
            if m.revision == revision:
                return m.upgrade_path.name
        return None

    def proceed_with_migration(self) -> bool:
        """Looks at:
         * the current version in the database
         * the verb that was requested... upgrade / status / current etc
         * and identifies what should be done.

        :return: True if the migration should proceed, False otherwise.
        :rtype: bool
        """
        verb = self.alembic_utils.get_alembic_verb()
        logger.debug("alembic command verb: %s", verb)
        if not verb:
            raise ValueError("Could not determine the alembic command verb. Cannot proceed with migration.")

        current_revision = self.alembic_helpers.get_current_revision()
        requested_revision = self.revision_management.get_requested_revision()

        current_file = self.get_migration_filename(current_revision)
        if current_revision and current_file:
            rev_str = f"{current_revision} - {current_file}"
        else:
            rev_str = f"{current_revision}"

        logger.info("🍄 Current DB revision: %s", rev_str)
        if verb == "current":
            print(f"🍄 Current DB revision: {rev_str}")
        if requested_revision:
            logger.info("Requested revision: %s", requested_revision)
        logger.debug("Requested verb: %s", verb)


        if verb == "current":
            return False

        # not sure this is correct
        if requested_revision is None:
            logger.info("No revision specified, defaulting to head")
            return True

        if verb.lower() == "upgrade":
            if current_revision and requested_revision and requested_revision not in ("head",) and not requested_revision.startswith("+"):
                try:
                    if self.alembic_utils.version_key(current_revision) > self.alembic_utils.version_key(requested_revision):
                        raise WrongDirectionError(
                            f"Cannot upgrade to {requested_revision} because it is lower than the current revision {current_revision}."
                        )
                except ValueError:
                    pass
        elif verb.lower() == "downgrade":
            if current_revision and requested_revision and requested_revision not in ("base",) and not requested_revision.startswith("-"):
                try:
                    if self.alembic_utils.version_key(current_revision) < self.alembic_utils.version_key(requested_revision):
                        raise WrongDirectionError(
                            f"Cannot downgrade to {requested_revision} because it is higher than the current revision {current_revision}."
                        )
                except ValueError:
                    pass
        elif verb.lower() in {"stamp", "baseline", "repair"}:
            return True
        return True

    def config_alembic_context(self):
        db_connection = self.db_conn.get_connection()
        version_table = self.alembic_helpers.get_version_table_name()
        version_table_schema = self.alembic_helpers.get_revision_table_schema()
        alembic.context.configure(
            connection=db_connection,
            target_metadata=None,
            version_table=version_table,
            version_table_schema=version_table_schema,
        )

class WrongDirectionError(RuntimeError):

    """Raised when an attempted upgrade or downgrade is in the wrong direction
    based on the current revision.  For example, trying to upgrade to a lower
    revision or downgrade to a higher revision."""
    pass


class MigrationSQLError(RuntimeError):
    """Raised when a statement in a migration script fails in Oracle.  Carries
    only the script path and the Oracle error so the user isn't buried in
    SQLAlchemy / driver tracebacks (those are still available with DEBUG=1)."""

    def __init__(self, script_path: pathlib.Path, oracle_message: str):
        self.script_path = script_path
        self.oracle_message = oracle_message
        super().__init__(f"Migration failed: {script_path}\n  {oracle_message}")


# ------------------------------------------------------------------------------
# Offline / Online entrypoints
# ------------------------------------------------------------------------------

def run_migrations_offline() -> None:
    raise NotImplementedError(
        "Offline mode is not implemented for raw SQL migrations in this env.py."
    )


def run_migrations_online() -> None:
    migs = AlembicMigrations()
    logger.debug("Starting online migration process...")
    migs.main()




def main_entrypoint():
    is_debug = logger.isEnabledFor(logging.DEBUG) or os.getenv("DEBUG", "").lower() in ("1", "true")
    if alembic.context.is_offline_mode():
        # ---------------------
        # --- OFFLINE HERE - Not implemented
        # ---------------------
        run_migrations_offline()
    else:
        try:
            # ---------------------
            # ---------------------
            run_migrations_online()
            logger.debug("done with online migration process")
        except WrongDirectionError as e:
            if is_debug:
                raise  # Re-raise with full traceback
            else:
                logger.info(f"{e}")

        except Exception as e:
            # Only show traceback if logger is at DEBUG level or DEBUG env var is set
            if is_debug:
                raise  # Re-raise with full traceback
            logger.error("%s", e)
            sys.exit(1)


if __name__ == "__main__" or (config is not None and getattr(config, "cmd_opts", None) is not None):
    main_entrypoint()

