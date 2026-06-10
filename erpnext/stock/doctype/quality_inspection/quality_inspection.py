# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt, get_link_to_form, get_number_format_info

from erpnext.stock.doctype.quality_inspection_template.quality_inspection_template import (
	get_template_details,
)


class QualityInspection(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from erpnext.stock.doctype.quality_inspection_reading.quality_inspection_reading import (
			QualityInspectionReading,
		)

		amended_from: DF.Link | None
		batch_no: DF.Link | None
		bom_no: DF.Link | None
		child_row_reference: DF.Data | None
		company: DF.Link | None
		description: DF.SmallText | None
		inspected_by: DF.Link
		inspection_basis: DF.Literal["Sample", "Each Quantity"]
		inspection_type: DF.Literal["", "Incoming", "Outgoing", "In Process"]
		item_code: DF.Link
		item_name: DF.Data | None
		serial_no: DF.Link | None
		letter_head: DF.Link | None
		manual_inspection: DF.Check
		naming_series: DF.Literal["MAT-QA-.YYYY.-"]
		quality_inspection_template: DF.Link | None
		reading_bundle: DF.Link | None
		readings: DF.Table[QualityInspectionReading]
		reference_name: DF.DynamicLink
		reference_type: DF.Literal[
			"",
			"Purchase Receipt",
			"Purchase Invoice",
			"Subcontracting Receipt",
			"Delivery Note",
			"Sales Invoice",
			"Stock Entry",
			"Job Card",
			"Quality Control Lot",
		]
		remarks: DF.Text | None
		report_date: DF.Date
		sample_size: DF.Float
		status: DF.Literal["", "Accepted", "Rejected", "Cancelled"]
		verified_by: DF.Data | None

	# end: auto-generated types
	def on_discard(self):
		self.update_qc_reference()
		self.db_set("status", "Cancelled")

	def validate(self):
		self.set_inspection_basis_from_lot()

		if self.inspection_basis != "Each Quantity" and not self.readings and self.item_code:
			self.get_item_specification_details()

		if (
			self.inspection_type == "In Process"
			and self.reference_type == "Job Card"
			and self.quality_inspection_template
		):
			parameters = get_template_details(self.quality_inspection_template)
			for reading in self.readings:
				for d in parameters:
					if reading.specification == d.specification:
						reading.update(d)
						reading.status = "Accepted"

		self.validate_reading_bundle_is_free()

		if self.readings:
			self.inspect_and_set_status()
		elif self.reading_bundle and not self.manual_inspection:
			self.set_status_from_reading_bundle()

		self.validate_inspection_required()
		self.set_child_row_reference()
		self.set_company()

	def set_company(self):
		if self.reference_type and self.reference_name:
			company = frappe.get_cached_value(self.reference_type, self.reference_name, "company")
			if company != self.company:
				self.company = company

	def set_child_row_reference(self):
		if self.child_row_reference:
			return

		if not (self.reference_type and self.reference_name):
			return

		# a Quality Control Lot has no item child table to reference
		if self.reference_type == "Quality Control Lot":
			return

		doctype = self.reference_type + " Item"
		if self.reference_type == "Stock Entry":
			doctype = "Stock Entry Detail"

		child_doc = frappe.qb.DocType(doctype)
		qi_doc = frappe.qb.DocType("Quality Inspection")

		child_row_references = (
			frappe.qb.from_(child_doc)
			.left_join(qi_doc)
			.on(child_doc.name == qi_doc.child_row_reference)
			.select(child_doc.name)
			.where(
				(child_doc.item_code == self.item_code)
				& (child_doc.parent == self.reference_name)
				& (child_doc.docstatus < 2)
				& (qi_doc.name.isnull())
			)
			.orderby(child_doc.idx)
		).run(pluck=True)

		if len(child_row_references):
			self.child_row_reference = child_row_references[0]

	def set_inspection_basis_from_lot(self):
		"""How the stock is inspected (Sample / Each Quantity).

		A Quality Control Lot carries its basis; inspections referencing a
		transaction resolve it from the item's quality trigger for that doctype.
		"""
		from erpnext.stock.services.quality_trigger_resolution import get_inspection_basis

		if self.reference_type == "Quality Control Lot" and self.reference_name:
			self.inspection_basis = (
				frappe.db.get_value("Quality Control Lot", self.reference_name, "inspection_basis")
				or "Sample"
			)
		elif self.reference_type and self.item_code:
			self.inspection_basis = get_inspection_basis(self.item_code, self.reference_type)
		else:
			self.inspection_basis = "Sample"

	def validate_reading_bundle_is_free(self):
		"""A reading bundle belongs to exactly one inspection."""
		if not self.reading_bundle:
			return

		owner = frappe.db.get_value(
			"Quality Inspection Reading Bundle", self.reading_bundle, "quality_inspection"
		)
		if owner and owner != self.name:
			frappe.throw(
				_("Reading Bundle {0} already belongs to Quality Inspection {1}.").format(
					frappe.bold(self.reading_bundle), get_link_to_form("Quality Inspection", owner)
				),
				title=_("Reading Bundle In Use"),
			)

	def sync_reading_bundle_link(self):
		"""Stamp the bundle with this inspection; release a bundle that was swapped out."""
		before = self.get_doc_before_save()
		previous_bundle = before.reading_bundle if before else None

		if previous_bundle and previous_bundle != self.reading_bundle:
			frappe.db.set_value(
				"Quality Inspection Reading Bundle", previous_bundle, "quality_inspection", None
			)

		if self.reading_bundle:
			frappe.db.set_value(
				"Quality Inspection Reading Bundle", self.reading_bundle, "quality_inspection", self.name
			)

	def set_status_from_reading_bundle(self):
		"""With per-unit readings, the verdict follows the bundle's unit counts."""
		accepted_qty = frappe.db.get_value(
			"Quality Inspection Reading Bundle", self.reading_bundle, "accepted_qty"
		)
		self.status = "Accepted" if accepted_qty else "Rejected"

	def validate_inspection_required(self):
		# Obsolete under the Item Quality Trigger model: Quality Inspection requirement is governed
		# by triggers on the transaction, not by per-Item flags or a global setting.
		pass

	def before_submit(self):
		self.validate_readings_status_mandatory()
		self.validate_readings_recorded()
		self.validate_reading_bundle_coverage()

	def validate_readings_recorded(self):
		"""The decision must rest on recorded readings.

		Draft saves leave unrecorded rows untouched, so without this gate an
		untouched row would pass on its default status. Manual rows, formula rows
		and manual inspections are exempt.
		"""
		if self.manual_inspection:
			return

		for reading in self.readings:
			if reading.manual_inspection or cint(reading.formula_based_criteria):
				continue
			if not self.has_recorded_reading(reading):
				frappe.throw(
					_("Row #{0}: Record a reading for {1} before submission.").format(
						reading.idx, frappe.bold(reading.specification)
					),
					title=_("Reading Missing"),
				)

	def validate_reading_bundle_coverage(self):
		"""An Each Quantity inspection's bundle must cover the stock it decides."""
		if self.inspection_basis != "Each Quantity" or not self.reading_bundle:
			return

		# a manual inspection's verdict overrides the per-unit machinery
		if self.manual_inspection:
			return

		bundle = frappe.db.get_value(
			"Quality Inspection Reading Bundle",
			self.reading_bundle,
			["item_code", "quantity"],
			as_dict=True,
		)
		if bundle.item_code != self.item_code:
			frappe.throw(
				_("Reading Bundle {0} is for item {1}, not {2}.").format(
					frappe.bold(self.reading_bundle),
					frappe.bold(bundle.item_code),
					frappe.bold(self.item_code),
				)
			)

		inspected_qty = self.get_qty_under_inspection()
		if inspected_qty and flt(bundle.quantity) != flt(inspected_qty):
			frappe.throw(
				_(
					"Reading Bundle {0} inspects {1} unit(s), but {2} are under inspection. Every "
					"unit needs its own readings on an Each Quantity basis."
				).format(frappe.bold(self.reading_bundle), bundle.quantity, inspected_qty),
				title=_("Incomplete Per-Unit Readings"),
			)

	@frappe.whitelist()
	def get_qty_under_inspection(self):
		if self.reference_type == "Quality Control Lot" and self.reference_name:
			return frappe.db.get_value("Quality Control Lot", self.reference_name, "pending_qty")

		if self.child_row_reference:
			child_doctype = (
				"Stock Entry Detail"
				if self.reference_type == "Stock Entry"
				else self.reference_type + " Item"
			)
			return frappe.db.get_value(child_doctype, self.child_row_reference, "qty")

		return None

	@frappe.whitelist()
	def get_item_specification_details(self):
		if not self.quality_inspection_template:
			return

		self.set("readings", [])
		parameters = get_template_details(self.quality_inspection_template)
		for d in parameters:
			child = self.append("readings", {})
			child.update(d)
			child.status = "Accepted"
			child.parameter_group = frappe.get_value(
				"Quality Inspection Parameter", d.specification, "parameter_group"
			)

	@frappe.whitelist()
	def get_quality_inspection_template(self):
		template = ""
		if self.bom_no:
			template = frappe.db.get_value("BOM", self.bom_no, "quality_inspection_template")

		if not template:
			template = frappe.db.get_value("BOM", self.item_code, "quality_inspection_template")

		self.quality_inspection_template = template
		self.get_item_specification_details()

	def on_update(self):
		self.update_qc_reference()
		self.sync_reading_bundle_link()

	def on_submit(self):
		self.update_qc_reference()

	def on_cancel(self):
		# the bundle is cancelled server-side below, in the right order — the
		# client cancel-all dialog must not try it first
		self.ignore_linked_doctypes = ("Serial and Batch Bundle", "Quality Inspection Reading Bundle")

		self.update_qc_reference()
		self.cancel_reading_bundle()

	def cancel_reading_bundle(self):
		"""A voided inspection voids its per-unit readings with it.

		The claim stays on the cancelled pair for the audit trail, so the
		readings can never decide other stock; re-inspection goes through an
		amended bundle.
		"""
		if not self.reading_bundle:
			return

		bundle = frappe.get_doc("Quality Inspection Reading Bundle", self.reading_bundle)
		if bundle.docstatus == 1:
			bundle.flags.ignore_permissions = True
			bundle.cancel()

	def on_trash(self):
		self.update_qc_reference(remove_reference=True)
		# release every bundle born from this inspection, not just the attached
		# one — orphan drafts would otherwise block the deletion
		for bundle in frappe.get_all(
			"Quality Inspection Reading Bundle", filters={"quality_inspection": self.name}, pluck="name"
		):
			frappe.db.set_value("Quality Inspection Reading Bundle", bundle, "quality_inspection", None)

	def validate_readings_status_mandatory(self):
		for reading in self.readings:
			if not reading.status:
				frappe.throw(_("Row #{0}: Status is mandatory").format(reading.idx))

	def update_qc_reference(self, remove_reference=False):
		quality_inspection = self.name if self.docstatus < 2 and not remove_reference else ""

		if self.reference_type == "Quality Control Lot":
			if self.reference_name:
				frappe.db.set_value(
					"Quality Control Lot", self.reference_name, "quality_inspection", quality_inspection
				)
			return

		if self.reference_type == "Job Card":
			if self.reference_name:
				frappe.db.sql(
					f"""
					UPDATE `tab{self.reference_type}`
					SET quality_inspection = %s, modified = %s
					WHERE name = %s and production_item = %s
				""",
					(quality_inspection, self.modified, self.reference_name, self.item_code),
				)

		else:
			doctype = self.reference_type + " Item"

			if self.reference_type == "Stock Entry":
				doctype = "Stock Entry Detail"

			if doctype and self.reference_name:
				child_doc = frappe.qb.DocType(doctype)

				query = (
					frappe.qb.update(child_doc)
					.set(child_doc.quality_inspection, quality_inspection)
					.where(
						(child_doc.parent == self.reference_name) & (child_doc.item_code == self.item_code)
					)
				)

				if self.batch_no and self.docstatus < 2:
					query = query.where(child_doc.batch_no == self.batch_no)

				if self.docstatus == 2:  # if cancel, then remove qi link wherever same name
					query = query.where(child_doc.quality_inspection == self.name)

				if self.child_row_reference:
					query = query.where(child_doc.name == self.child_row_reference)

				query.run()

				frappe.db.set_value(
					self.reference_type,
					self.reference_name,
					"modified",
					self.modified,
				)

	def inspect_and_set_status(self):
		for reading in self.readings:
			if not reading.manual_inspection:  # dont auto set status if manual
				if reading.formula_based_criteria:
					self.set_status_based_on_acceptance_formula(reading)
				else:
					# if not formula based check acceptance values set
					self.set_status_based_on_acceptance_values(reading)

		if not self.manual_inspection:
			self.status = "Accepted"
			for reading in self.readings:
				if reading.status == "Rejected":
					self.status = "Rejected"
					frappe.msgprint(
						_("Status set to rejected as there are one or more rejected readings."), alert=True
					)
					break

	def set_status_based_on_acceptance_values(self, reading):
		# an unrecorded reading is a draft in progress, not a failure: leave its
		# status alone — submission separately demands that readings be recorded
		if not self.has_recorded_reading(reading):
			return

		if not cint(reading.numeric):
			# compare case-insensitively and ignore surrounding whitespace, so a
			# reading of "yes" passes an acceptance criteria of "Yes"
			reading_value = (reading.get("reading_value") or "").strip().casefold()
			value = (reading.get("value") or "").strip().casefold()
			result = reading_value == value
		else:
			# numeric readings
			result = self.min_max_criteria_passed(reading)

		reading.status = "Accepted" if result else "Rejected"

	@staticmethod
	def has_recorded_reading(reading):
		if not cint(reading.numeric):
			return bool((reading.get("reading_value") or "").strip())
		return any((reading.get(f"reading_{i}") or "").strip() for i in range(1, 11))

	def min_max_criteria_passed(self, reading):
		"""Determine whether all readings fall in the acceptable range."""
		has_reading = False
		for i in range(1, 11):
			reading_value = reading.get("reading_" + str(i))
			if reading_value is not None and reading_value.strip():
				has_reading = True
				result = (
					flt(reading.get("min_value"))
					<= parse_float(reading_value)
					<= flt(reading.get("max_value"))
				)
				if not result:
					return False
		return has_reading

	def set_status_based_on_acceptance_formula(self, reading):
		if not reading.acceptance_formula:
			frappe.throw(
				_("Row #{0}: Acceptance Criteria Formula is required.").format(reading.idx),
				title=_("Missing Formula"),
			)

		condition = reading.acceptance_formula
		data = self.get_formula_evaluation_data(reading)

		try:
			result = frappe.safe_eval(condition, None, data)
			reading.status = "Accepted" if result else "Rejected"
		except NameError as e:
			field = frappe.bold(e.args[0].split()[1])
			frappe.throw(
				_(
					"Row #{0}: {1} is not a valid reading field. Please refer to the field description."
				).format(reading.idx, field),
				title=_("Invalid Formula"),
			)
		except Exception:
			frappe.throw(
				_("Row #{0}: Acceptance Criteria Formula is incorrect.").format(reading.idx),
				title=_("Invalid Formula"),
			)

	def get_formula_evaluation_data(self, reading):
		data = {}
		if not cint(reading.numeric):
			data = {"reading_value": reading.get("reading_value")}
		else:
			# numeric readings
			for i in range(1, 11):
				field = "reading_" + str(i)
				if reading.get(field) is None:
					data[field] = 0.0
					continue

				data[field] = parse_float(reading.get(field))
			data["mean"] = self.calculate_mean(reading)

		return data

	def calculate_mean(self, reading):
		"""Calculate mean of all non-empty readings."""
		from statistics import mean

		readings_list = []

		for i in range(1, 11):
			reading_value = reading.get("reading_" + str(i))
			if reading_value is not None and reading_value.strip():
				readings_list.append(parse_float(reading_value))

		actual_mean = mean(readings_list) if readings_list else 0
		return actual_mean


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype: Any, txt: str | None, searchfield: Any, start: int, page_len: int, filters: dict):
	reference_doctype = filters.get("reference_doctype")

	if not reference_doctype:
		return []
	elif reference_doctype == "Job Card":
		production_item, item_name = frappe.get_value(
			"Job Card", filters.get("reference_name"), ["production_item", "item_name"]
		)
		return ((production_item, item_name),)
	elif reference_doctype == "Quality Control Lot":
		# a lot quarantines exactly one item; it has no items child table
		item_code = frappe.get_value("Quality Control Lot", filters.get("reference_name"), "item_code")
		if not item_code:
			return []
		return ((item_code, frappe.get_cached_value("Item", item_code, "item_name")),)
	else:
		my_filters = [
			["items.parent", "=", filters.get("reference_name")],
			"and",
			["items.item_code", "like", f"%{txt}%"],
			"and",
			["docstatus", "<", 2],
			"and",
			["items.quality_inspection", "is", "not set"],
		]

		if reference_doctype == "Stock Entry":
			my_filters.extend(
				[
					"and",
					["items.t_warehouse", "is", "not set"],
				]
			)

		return frappe.get_query(
			reference_doctype,
			fields=["items.item_code, items.item_name"],
			filters=my_filters,
			offset=start,
			limit=page_len,
			order_by="items.item_code",
			ignore_permissions=False,
			distinct=True,
		).run()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def quality_inspection_query(
	doctype: Any, txt: str | None, searchfield: Any, start: int, page_len: int, filters: dict
):
	return frappe.get_all(
		"Quality Inspection",
		limit_start=start,
		limit_page_length=page_len,
		filters={
			"docstatus": ("<", 2),
			"name": ("like", "%%%s%%" % txt),
			"item_code": filters.get("item_code"),
			"reference_name": ("in", [filters.get("reference_name", ""), ""]),
			"child_row_reference": ("in", [filters.get("child_row_reference", ""), ""]),
		},
		as_list=1,
	)


@frappe.whitelist()
def make_quality_inspection(source_name: str, target_doc: Document | str | None = None):
	def postprocess(source, doc):
		doc.inspected_by = frappe.session.user
		doc.get_quality_inspection_template()

	doc = get_mapped_doc(
		"BOM",
		source_name,
		{
			"BOM": {
				"doctype": "Quality Inspection",
				"validation": {"docstatus": ["=", 1]},
				"field_map": {"name": "bom_no", "item": "item_code", "stock_uom": "uom", "stock_qty": "qty"},
			}
		},
		target_doc,
		postprocess,
	)

	return doc


@frappe.whitelist()
def make_reading_bundle(quality_inspection: str):
	"""A reading bundle born from its inspection, fully formed.

	Created server-side because the client's route options skip no_copy fields —
	the inspection backlink would be dropped and the bundle born unlinked.
	"""
	inspection = frappe.get_doc("Quality Inspection", quality_inspection)
	bundle = frappe.new_doc("Quality Inspection Reading Bundle")
	bundle.quality_inspection = inspection.name
	bundle.item_code = inspection.item_code
	bundle.quality_inspection_template = inspection.quality_inspection_template
	bundle.quantity = cint(inspection.get_qty_under_inspection())
	return bundle


def parse_float(num: str) -> float:
	"""Since reading_# fields are `Data` field they might contain number which
	is representation in user's prefered number format instead of machine
	readable format. This function converts them to machine readable format."""

	number_format = frappe.db.get_default("number_format") or "#,###.##"
	decimal_str, comma_str, _number_format_precision = get_number_format_info(number_format)

	if decimal_str == "," and comma_str == ".":
		num = num.replace(",", "#$")
		num = num.replace(".", ",")
		num = num.replace("#$", ".")

	return flt(num)
